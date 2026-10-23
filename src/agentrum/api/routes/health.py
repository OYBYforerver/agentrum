from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import __version__
from agentrum.db.engine import get_session

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "ok", "name": "agentrum", "version": __version__}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict:
    """Readiness: the process can serve traffic (database reachable)."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any DB failure means "not ready"
        raise HTTPException(status_code=503, detail="database not ready") from None
    return {"status": "ready", "version": __version__}
