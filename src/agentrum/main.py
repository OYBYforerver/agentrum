"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from agentrum import __version__
from agentrum.api.middleware import BodySizeLimitMiddleware, RequestIDMiddleware
from agentrum.api.router import api_router
from agentrum.api.routes.teams import install_error_handlers
from agentrum.auth import security
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal
from agentrum.logging_setup import configure_logging
from agentrum.services import (
    maintenance_service,
    notification_dispatcher,
    probe_service,
)
from agentrum.services.deployments import reconciler as deployments_reconciler

logger = logging.getLogger("agentrum.main")


async def _ensure_bootstrap_admin() -> None:
    """Create the first platform admin on an empty database."""
    settings = get_settings()
    try:
        async with SessionLocal() as session:
            count = (
                await session.execute(select(func.count()).select_from(models.User))
            ).scalar_one()
            if count:
                return
            session.add(
                models.User(
                    username=settings.bootstrap_admin_username,
                    password_hash=security.hash_password(settings.bootstrap_admin_password),
                    is_platform_admin=True,
                )
            )
            await session.commit()
        logger.warning(
            "Bootstrapped platform admin %r with a default password. "
            "Set ARK_BOOTSTRAP_ADMIN_PASSWORD before production use!",
            settings.bootstrap_admin_username,
        )
    except Exception:
        logger.exception("bootstrap admin creation failed; is the database reachable?")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _ensure_bootstrap_admin()
    tasks = [
        notification_dispatcher.start_dispatcher(),
        deployments_reconciler.start_controller(),
        probe_service.start_prober(),
        maintenance_service.start_maintenance(),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        import asyncio

        await asyncio.gather(*tasks, return_exceptions=True)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_format)

    app = FastAPI(
        title="Agentrum",
        description=(
            "Multi-tenant registry for AI agents, MCP servers, skills and prompts. "
            "Publish, subscribe, run."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RequestIDMiddleware)

    app.include_router(api_router)
    install_error_handlers(app)

    if settings.otel_enabled:
        _setup_tracing(app)
    instrumentator(app)

    return app


def instrumentator(app: FastAPI) -> None:
    """Prometheus /metrics endpoint."""
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(should_group_status_codes=False).instrument(app).expose(
        app, include_in_schema=False
    )


def _setup_tracing(app: FastAPI) -> None:
    """OTLP tracing, enabled with ARK_OTEL_ENABLED=true."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    settings = get_settings()
    provider = TracerProvider(resource=Resource.create({"service.name": "agentrum"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OpenTelemetry tracing enabled -> %s", settings.otel_endpoint)


app = create_app()
