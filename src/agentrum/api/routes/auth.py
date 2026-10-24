import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit
from agentrum.auth import security
from agentrum.auth.deps import client_ip, get_current_user
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
# Per-username lockout across all source IPs: an attacker behind one egress
# IP cannot lock out a victim by spraying failures with that IP.
_username_lockout = FailureLockout(
    threshold=_settings.lockout_username_threshold,
    window_seconds=_settings.lockout_seconds,
    lock_seconds=_settings.lockout_seconds,
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)
) -> TokenOut:
    ip = client_ip(request) or "unknown"
    key = f"{body.username}|{ip}"

    locked_for = max(_lockout.is_locked(key), _username_lockout.is_locked(body.username))
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
    if user is None:
        # Same Argon2 work as the failure path so response timing does not
        # reveal whether the username exists.
        security.dummy_verify(body.password)
    if user is None or not security.verify_password(body.password, user.password_hash):
        _lockout.record_failure(key)
        _username_lockout.record_failure(body.username)
        await audit.record(
            session, actor=None, action="user.login_failed",
            detail={"username": body.username}, source_ip=ip,
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="invalid username or password")
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="account is disabled")
    _lockout.reset(key)
    _username_lockout.reset(body.username)
    await audit.record(
        session, actor=user, action="user.login", source_ip=ip,
    )
    await session.commit()
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
    # Invalidate every session issued before now (JWTs carry their iat).
    user.password_changed_at = datetime.now(UTC)
    await audit.record(
        session, actor=user, action="user.change_password",
        source_ip=client_ip(request),
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
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiTokenCreatedOut:
    days = body.expires_in_days
    if days is None:
        days = _settings.api_token_default_expire_days
    if days < 1 or days > _settings.api_token_max_expire_days:
        raise HTTPException(
            status_code=400,
            detail=f"expires_in_days must be 1-{_settings.api_token_max_expire_days}",
        )
    raw, token_hash = security.new_api_token()
    row = models.ApiToken(
        user_id=user.id,
        name=body.name,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    session.add(row)
    await audit.record(
        session, actor=user, action="api_token.create",
        detail={"name": body.name, "expires_in_days": days},
        source_ip=client_ip(request),
    )
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
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        token_uuid = uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="token not found") from None
    row = await session.get(models.ApiToken, token_uuid)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="token not found")
    row.revoked_at = datetime.now(UTC)
    await audit.record(
        session, actor=user, action="api_token.revoke",
        detail={"name": row.name}, source_ip=client_ip(request),
    )
    await session.commit()
