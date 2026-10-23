from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth.deps import require_platform_admin
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.services import team_service

router = APIRouter()


@router.get("", response_model=list[dict])
async def list_audit(
    limit: int = 50,
    offset: int = 0,
    _admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    limit = max(1, min(limit, 200))
    rows = (
        await session.execute(
            select(models.AuditLog)
            .order_by(models.AuditLog.occurred_at.desc())
            .limit(limit)
            .offset(max(0, offset))
        )
    ).scalars().all()
    names = await team_service.usernames(session, [r.actor_user_id for r in rows])
    return [
        {
            "id": r.id,
            "occurred_at": r.occurred_at.isoformat(),
            "actor": names.get(r.actor_user_id),
            "action": r.action,
            "kind": r.kind,
            "namespace": r.namespace,
            "name": r.name,
            "detail": r.detail or {},
            "source_ip": r.source_ip,
        }
        for r in rows
    ]
