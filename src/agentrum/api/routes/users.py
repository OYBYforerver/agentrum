"""User management (platform admin only in the MVP)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth import security
from agentrum.auth.deps import require_platform_admin
from agentrum.db import models
from agentrum.db.engine import get_session

router = APIRouter()


class UserCreateIn(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    is_platform_admin: bool


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateIn,
    _admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    if not body.username or len(body.username) > 63:
        raise HTTPException(status_code=400, detail="username must be 1-63 chars")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 chars")
    dup = (
        await session.execute(select(models.User).where(models.User.username == body.username))
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="username already taken")
    user = models.User(
        username=body.username,
        password_hash=security.hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserOut(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
    )


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UserOut]:
    rows = (
        await session.execute(select(models.User).order_by(models.User.username))
    ).scalars().all()
    return [
        UserOut(
            id=str(u.id), username=u.username, display_name=u.display_name,
            is_platform_admin=u.is_platform_admin,
        )
        for u in rows
    ]
