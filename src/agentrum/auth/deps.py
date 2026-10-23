"""FastAPI dependencies: resolve JWT or API-token credentials into a User."""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth import security
from agentrum.db import models
from agentrum.db.engine import get_session

bearer_scheme = HTTPBearer(auto_error=False)


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
    if user is not None:
        await session.execute(
            update(models.ApiToken)
            .where(models.ApiToken.id == row.id)
            .values(last_used_at=now)
        )
        await session.commit()
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> models.User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await _resolve_credential(session, credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_platform_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin required")
    return user
