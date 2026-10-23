import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit
from agentrum.auth import security
from agentrum.auth.deps import get_current_user
from agentrum.auth.ratelimit import FailureLockout, SlidingWindowLimiter
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.schemas.auth import (
    ApiTokenCreatedOut,
    ApiTokenCreateIn,
    ApiTokenOut,
    LoginIn,
    MeOut,
    PasswordChangeIn,
    TokenOut,
)

router = APIRouter()

_settings = get_settings()
_login_limiter = SlidingWindowLimiter(
    max_events=_settings.login_max_per_window,
    window_seconds=_settings.login_window_seconds,
)
_lockout = FailureLockout(
    threshold=_settings.lockout_threshold,
    window_seconds=_settings.lockout_seconds,
    lock_seconds=_settings.lockout_seconds,
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)
) -> TokenOut:
    ip = request.client.host if request.client else "unknown"
    key = f"{body.username}|{ip}"

    locked_for = _lockout.is_locked(key)
    if locked_for:
        raise HTTPException(
            status_code=429,
            detail=f"account temporarily locked, retry in {locked_for}s",
        )
    if not _login_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="too many login attempts, slow down")

    user = (
        await session.execute(select(models.User).where(models.User.username == body.username))
    ).scalar_one_or_none()
    if user is None or not security.verify_password(body.password, user.password_hash):
        _lockout.record_failure(key)
        raise HTTPException(status_code=401, detail="invalid username or password")
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="account is disabled")
    _lockout.reset(key)
    return TokenOut(access_token=security.create_access_token(user.id))


@router.post("/change-password", status_code=204)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    if not security.verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=403, detail="old password incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="new password must be at least 8 chars")
    user.password_hash = security.hash_password(body.new_password)
    await audit.record(
        session, actor=user, action="user.change_password",
        source_ip=request.client.host if request.client else None,
    )
    await session.commit()


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
