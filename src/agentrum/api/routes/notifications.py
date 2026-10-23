from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth.deps import require_platform_admin
from agentrum.db import models
from agentrum.db.engine import get_session

router = APIRouter()


@router.get("", response_model=list[dict])
async def list_outbox(
    status: str = "pending",
    limit: int = 50,
    _admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Observability for the notification pipeline (platform admin)."""
    limit = max(1, min(limit, 200))
    stmt = select(models.NotificationOutbox).order_by(models.NotificationOutbox.id.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(models.NotificationOutbox.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "event": r.event_type,
            "status": r.status,
            "attempts": r.attempts,
            "next_attempt_at": r.next_attempt_at.isoformat(),
            "last_error": r.last_error,
            "payload": r.payload,
        }
        for r in rows
    ]
