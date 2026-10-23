"""Project-scoped AK/SK management (machine credentials)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit
from agentrum.auth import security
from agentrum.auth.ak_context import AK_SCOPES
from agentrum.auth.deps import get_current_user
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.services import team_service

router = APIRouter()


class AccessKeyCreateIn(BaseModel):
    name: str
    scopes: list[str] = ["read", "publish", "deploy"]
    expires_in_days: int | None = None


class AccessKeyOut(BaseModel):
    id: str
    name: str
    access_key: str
    scopes: list
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked: bool


class AccessKeyCreatedOut(AccessKeyOut):
    secret: str  # plaintext SK, returned exactly once


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _out(row: models.AccessKey) -> AccessKeyOut:
    return AccessKeyOut(
        id=str(row.id),
        name=row.name,
        access_key=row.access_key,
        scopes=row.scopes or [],
        created_at=_iso(row.created_at) or "",
        last_used_at=_iso(row.last_used_at),
        expires_at=_iso(row.expires_at),
        revoked=row.revoked_at is not None,
    )


@router.post("/{team_name}/access-keys", response_model=AccessKeyCreatedOut, status_code=201)
async def create_access_key(
    team_name: str,
    body: AccessKeyCreateIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AccessKeyCreatedOut:
    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, user, team, minimum=models.ROLE_ADMIN)
    bad = [s for s in body.scopes if s not in AK_SCOPES]
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown scopes: {bad}")
    if not body.scopes:
        raise HTTPException(status_code=400, detail="at least one scope required")
    ak, sk, sk_hash = security.new_access_key()
    row = models.AccessKey(
        project_id=team.id,
        access_key=ak,
        secret_hash=sk_hash,
        name=body.name,
        scopes=body.scopes,
        created_by=user.id,
        expires_at=(
            datetime.now(UTC) + timedelta(days=body.expires_in_days)
            if body.expires_in_days
            else None
        ),
    )
    session.add(row)
    await audit.record(
        session, actor=user, action="access_key.create", detail={
            "team": team_name, "name": body.name, "scopes": body.scopes,
        },
        source_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(row)
    return AccessKeyCreatedOut(
        secret=sk,
        **_out(row).model_dump(),
    )


@router.get("/{team_name}/access-keys", response_model=list[AccessKeyOut])
async def list_access_keys(
    team_name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AccessKeyOut]:
    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, user, team, minimum=models.ROLE_ADMIN)
    rows = (
        await session.execute(
            select(models.AccessKey)
            .where(models.AccessKey.project_id == team.id)
            .order_by(models.AccessKey.created_at.desc())
        )
    ).scalars().all()
    return [_out(r) for r in rows]


@router.delete("/{team_name}/access-keys/{key_id}", status_code=204)
async def revoke_access_key(
    team_name: str,
    key_id: str,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, user, team, minimum=models.ROLE_ADMIN)
    row = await session.get(models.AccessKey, uuid.UUID(key_id))
    if row is None or row.project_id != team.id:
        raise HTTPException(status_code=404, detail="access key not found")
    row.revoked_at = datetime.now(UTC)
    await audit.record(
        session, actor=user, action="access_key.revoke", detail={
            "team": team_name, "access_key": row.access_key,
        },
        source_ip=request.client.host if request.client else None,
    )
    await session.commit()
