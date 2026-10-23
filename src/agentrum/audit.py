"""Audit logging: every mutating action goes through `record`."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.db import models


async def record(
    session: AsyncSession,
    *,
    actor: models.User | None,
    action: str,
    kind: str | None = None,
    namespace: str | None = None,
    name: str | None = None,
    detail: dict[str, Any] | None = None,
    source_ip: str | None = None,
) -> None:
    """Append an audit entry. The caller is responsible for committing."""
    session.add(
        models.AuditLog(
            actor_user_id=actor.id if actor else None,
            action=action,
            kind=kind,
            namespace=namespace,
            name=name,
            detail=detail or {},
            source_ip=source_ip,
        )
    )
