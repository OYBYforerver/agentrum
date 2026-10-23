import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth import security
from agentrum.auth.deps import get_current_user
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.schemas.auth import (
    ApiTokenCreatedOut,
    ApiTokenCreateIn,
    ApiTokenOut,
    LoginIn,
    MeOut,
    TokenOut,
)

router = APIRouter()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = (
        await session.execute(select(models.User).where(models.User.username == body.username))
    ).scalar_one_or_none()
    if user is None or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    return TokenOut(access_token=security.create_access_token(user.id))


@router.get("/me", response_model=MeOut)
async def me(user: models.User = Depends(get_current_user)) -> MeOut:
    return MeOut(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
        teams=[],
    )


@router.post("/tokens", response_model=ApiTokenCreatedOut, status_code=201)
async def create_token(
    body: ApiTokenCreateIn,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiTokenCreatedOut:
    raw, token_hash = security.new_api_token()
    row = models.ApiToken(user_id=user.id, name=body.name, token_hash=token_hash)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiTokenCreatedOut(
        token=raw,
        id=str(row.id),
        name=row.name,
        created_at=_iso(row.created_at) or datetime.now(UTC).isoformat(),
    )


@router.get("/tokens", response_model=list[ApiTokenOut])
async def list_tokens(
    user: models.User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[ApiTokenOut]:
    rows = (
        await session.execute(
            select(models.ApiToken)
            .where(models.ApiToken.user_id == user.id)
            .order_by(models.ApiToken.created_at.desc())
        )
    ).scalars().all()
    return [
        ApiTokenOut(
            id=str(r.id),
            name=r.name,
            created_at=_iso(r.created_at) or "",
            last_used_at=_iso(r.last_used_at),
            expires_at=_iso(r.expires_at),
            revoked_at=_iso(r.revoked_at),
        )
        for r in rows
    ]


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(models.ApiToken, uuid.UUID(token_id))
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="token not found")
    row.revoked_at = datetime.now(UTC)
    await session.commit()
