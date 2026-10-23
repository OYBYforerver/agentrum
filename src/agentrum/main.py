"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from agentrum import __version__
from agentrum.api.router import api_router
from agentrum.api.routes.teams import install_error_handlers
from agentrum.auth import security
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

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
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentrum",
        description=(
            "Multi-tenant registry for AI agents, MCP servers, skills and prompts. "
            "Publish, subscribe, run."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    install_error_handlers(app)

    return app


app = create_app()
