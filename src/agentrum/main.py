"""FastAPI application factory."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from agentrum import __version__
from agentrum.api.error_handlers import install_error_handlers
from agentrum.api.middleware import (
    BodySizeLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    StaticConsoleMiddleware,
)
from agentrum.api.router import api_router
from agentrum.auth import security
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal
from agentrum.logging_setup import configure_logging
from agentrum.services import (
    git_service,
    maintenance_service,
    notification_dispatcher,
    probe_service,
)
from agentrum.services.deployments import reconciler as deployments_reconciler

logger = logging.getLogger("agentrum.main")


async def _ensure_bootstrap_admin() -> None:
    """Create the first platform admin on an empty database.

    With the default bootstrap password an insecure deployment gets a random
    one, printed exactly once, so `admin/admin123` is never silently live in
    production (opt back in with ARK_ALLOW_INSECURE=true for local dev).
    """
    settings = get_settings()
    try:
        password = settings.bootstrap_admin_password
        if (
            password == settings.DEFAULT_BOOTSTRAP_PASSWORD
            and not settings.allow_insecure
        ):
            password = secrets.token_urlsafe(12)
        async with SessionLocal() as session:
            count = (
                await session.execute(select(func.count()).select_from(models.User))
            ).scalar_one()
            if count:
                return
            session.add(
                models.User(
                    username=settings.bootstrap_admin_username,
                    password_hash=security.hash_password(password),
                    is_platform_admin=True,
                )
            )
            await session.commit()
        if password != settings.bootstrap_admin_password:
            logger.warning(
                "Bootstrapped platform admin %r with a GENERATED password: %s  "
                "(shown once; set ARK_BOOTSTRAP_ADMIN_PASSWORD to control it)",
                settings.bootstrap_admin_username,
                password,
            )
        else:
            logger.warning(
                "Bootstrapped platform admin %r with a default password. "
                "Set ARK_BOOTSTRAP_ADMIN_PASSWORD before production use!",
                settings.bootstrap_admin_username,
            )
    except Exception:
        logger.exception("bootstrap admin creation failed; is the database reachable?")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from agentrum.mcp_server import mcp as _mcp

    mcp_lifespan = _mcp.session_manager.run()  # async CM (manager created at import)
    await mcp_lifespan.__aenter__()
    tasks = []
    try:
        await _ensure_bootstrap_admin()
        tasks = [
            notification_dispatcher.start_dispatcher(),
            deployments_reconciler.start_controller(),
            probe_service.start_prober(),
            maintenance_service.start_maintenance(),
            git_service.start_drift_checker(),
        ]
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await mcp_lifespan.__aexit__(None, None, None)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.assert_safe_secrets()
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

    # Added first → runs innermost, so CORS and request-id still wrap it.
    if settings.ui_dir and Path(settings.ui_dir).is_dir():
        app.add_middleware(StaticConsoleMiddleware, ui_dir=settings.ui_dir)
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
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(api_router)
    install_error_handlers(app)

    # Bundled onboarding handbook (built mkdocs site) — mount BEFORE the
    # catch-all MCP mount below, or /handbook/* would fall into it.
    if settings.docs_dir and Path(settings.docs_dir).is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/handbook", StaticFiles(directory=settings.docs_dir, html=True), name="handbook")

    if settings.metrics_enabled:
        instrumentator(app)

    # Registry-as-MCP-server: IDE-facing read-only tools at /mcp
    # (mounted at root: the sub-app itself serves POST /mcp; its session
    # manager runs inside our lifespan to avoid "task group not initialized").
    # Mounted LAST so /metrics, /handbook and the API routes match first.
    from agentrum.mcp_server import mcp

    app.mount("/", mcp.streamable_http_app())

    if settings.otel_enabled:
        _setup_tracing(app)

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
