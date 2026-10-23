"""FastAPI dependencies: resolve JWT, API-token or AK/SK credentials."""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth import security
from agentrum.auth.ak_context import ak_project_id_var, ak_scopes_var
from agentrum.db import models
from agentrum.db.engine import get_session

bearer_scheme = HTTPBearer(auto_error=False)
basic_scheme = HTTPBasic(auto_error=False)


async def _resolve_credential(session: AsyncSession, credential: str) -> models.User | None:
    # 1) JWT session token
    try:
        user_id = security.decode_access_token(credential)
        return await session.get(models.User, user_id)
    except ValueError:
        pass

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
    await session.execute(
        update(models.ApiToken)
        .where(models.ApiToken.id == row.id)
        .values(last_used_at=now)
    )
    await session.commit()
    return user


async def _resolve_access_key(
    request: Request, session: AsyncSession, username: str, password: str
) -> models.User:
    """Authenticate a project AK/SK pair (HTTP Basic). The acting principal
    is the key's creator; project + scopes travel via contextvars so the
    authorization layer can enforce project-scoped access."""
    row = (
        await session.execute(
            select(models.AccessKey).where(models.AccessKey.access_key == username)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        row is None
        or row.revoked_at is not None
        or row.secret_hash != security.hash_api_token(password)
        or (row.expires_at is not None and row.expires_at < now)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AK/SK")
    project = await session.get(models.Team, row.project_id)
    owner = await session.get(models.User, row.created_by)
    if project is None or owner is None or owner.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AK/SK unusable")
    unknown = [s for s in (row.scopes or []) if s not in ("read", "publish", "deploy")]
    if unknown:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AK scopes")

    ak_project_id_var.set(str(project.id))
    ak_scopes_var.set(tuple(row.scopes or []))
    await session.execute(
        update(models.AccessKey)
        .where(models.AccessKey.id == row.id)
        .values(last_used_at=now)
    )
    await session.commit()
    return owner


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    basic: HTTPBasicCredentials | None = Depends(basic_scheme),
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
