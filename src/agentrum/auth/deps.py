"""FastAPI dependencies: resolve JWT, API-token or AK/SK credentials."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit, errors
from agentrum.auth import security
from agentrum.auth.ak_context import AK_SCOPES, ak_project_id_var, ak_scopes_var
from agentrum.auth.ratelimit import FailureLockout, SlidingWindowLimiter
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.services import team_service

bearer_scheme = HTTPBearer(auto_error=False)
basic_scheme = HTTPBasic(auto_error=False)

_settings = get_settings()
# Brute-force throttling for machine credentials (human logins have their own
# in the auth route): per-AK sliding window + lockout.
_ak_limiter = SlidingWindowLimiter(
    max_events=_settings.login_max_per_window * 6,
    window_seconds=_settings.login_window_seconds,
)
_ak_lockout = FailureLockout(
    threshold=_settings.lockout_threshold * 3,
    window_seconds=_settings.lockout_seconds,
    lock_seconds=_settings.lockout_seconds,
)

# Updating last_used_at on every request doubles write traffic and serializes
# concurrent requests on the row lock; once a minute is plenty.
_LAST_USED_MIN_INTERVAL = timedelta(seconds=60)


def client_ip(request: Request | None) -> str | None:
    """Client IP for rate limiting / audit. With ARK_CLIENT_IP_HEADER set
    (reverse proxy deployments), the first hop of that header is used."""
    if request is None:
        return None
    if _settings.client_ip_header:
        forwarded = request.headers.get(_settings.client_ip_header)
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _touch_last_used(row, now: datetime) -> bool:  # type: ignore[no-untyped-def]
    """Return True when last_used_at should be rewritten (throttled)."""
    return row.last_used_at is None or (now - row.last_used_at) >= _LAST_USED_MIN_INTERVAL


async def _resolve_credential(session: AsyncSession, credential: str) -> models.User | None:
    # 1) JWT session token
    try:
        user_id, issued_at = security.decode_access_token(credential)
    except ValueError:
        issued_at = None
    else:
        user = await session.get(models.User, user_id)
        if user is None:
            return None
        # Password change/reset revokes sessions issued before that instant.
        if (
            issued_at is not None
            and user.password_changed_at is not None
            and issued_at < user.password_changed_at
        ):
            return None
        return user

    # 2) Long-lived API token (hashed lookup)
    token_hash = security.hash_api_token(credential)
    row = (
        await session.execute(
            select(models.ApiToken).where(
                models.ApiToken.token_hash == token_hash,
                models.ApiToken.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(UTC)
    if row.expires_at is not None and row.expires_at < now:
        return None
    user = await session.get(models.User, row.user_id)
    if user is None or user.disabled_at is not None:
        return None
    if _touch_last_used(row, now):
        await session.execute(
            update(models.ApiToken)
            .where(models.ApiToken.id == row.id)
            .values(last_used_at=now)
        )
        await session.commit()
    return user


def _minimum_role_for(scopes: list[str]) -> str | None:
    """Team role the key's creator must still hold for these scopes."""
    if "deploy" in scopes:
        return models.ROLE_ADMIN
    if "publish" in scopes:
        return models.ROLE_DEVELOPER
    return models.ROLE_MEMBER


async def _resolve_access_key(
    request: Request | None, session: AsyncSession, username: str, password: str,
    enforce_ip_limit: bool = True,
) -> models.User:
    """Authenticate a project AK/SK pair (HTTP Basic). The acting principal
    is the key's creator; project + scopes travel via contextvars so the
    authorization layer can enforce project-scoped access.

    `request=None` (MCP server-side calls) skips the per-IP limiter — every
    MCP call shares the server's own address — but keeps the per-AK lockout
    so online SK guessing still trips a breaker."""
    ip = client_ip(request) or "unknown"
    if enforce_ip_limit and not _ak_limiter.allow(f"ak:{ip}"):
        raise HTTPException(status_code=429, detail="too many requests, slow down")
    locked_for = _ak_lockout.is_locked(f"ak:{username}")
    if locked_for:
        raise HTTPException(
            status_code=429,
            detail=f"access key temporarily locked, retry in {locked_for}s",
        )

    async def _fail(detail: str) -> None:
        _ak_lockout.record_failure(f"ak:{username}")
        await audit.record(
            session, actor=None, action="access_key.auth_failed",
            detail={"access_key": username, "reason": detail}, source_ip=ip,
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    row = (
        await session.execute(
            select(models.AccessKey).where(models.AccessKey.access_key == username)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None:
        await _fail("Invalid AK/SK")
    if row.secret_hash != security.hash_api_token(password) or (
        row.expires_at is not None and row.expires_at < now
    ):
        await _fail("Invalid AK/SK")
    project = await session.get(models.Team, row.project_id)
    owner = await session.get(models.User, row.created_by)
    if project is None or owner is None or owner.disabled_at is not None:
        await _fail("AK/SK unusable")
    unknown = [s for s in (row.scopes or []) if s not in AK_SCOPES]
    if unknown:
        await _fail("Invalid AK scopes")
    # The key's authority is a snapshot of its creator's role at creation
    # time; re-check that the creator is still entitled (demotion/removal
    # must take the key's powers with it).
    if not owner.is_platform_admin:
        try:
            await team_service.require_member(
                session, owner, project, minimum=_minimum_role_for(row.scopes or [])
            )
        except errors.PermissionDeniedError:
            await _fail("AK creator no longer authorized in the project")

    ak_project_id_var.set(str(project.id))
    ak_scopes_var.set(tuple(row.scopes or []))
    if _touch_last_used(row, now):
        await session.execute(
            update(models.AccessKey)
            .where(models.AccessKey.id == row.id, models.AccessKey.revoked_at.is_(None))
            .values(last_used_at=now)
        )
        await session.commit()
    return owner


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    basic: Annotated[HTTPBasicCredentials | None, Depends(basic_scheme)] = None,
    session: AsyncSession = Depends(get_session),
) -> models.User:
    # Reset AK context so it never leaks between requests on reused tasks.
    ak_project_id_var.set(None)
    ak_scopes_var.set(())

    user: models.User | None = None
    if credentials is not None and credentials.credentials:
        user = await _resolve_credential(session, credentials.credentials)
    elif basic is not None:
        user = await _resolve_access_key(request, session, basic.username, basic.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    return user


def require_platform_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin required")
    return user
