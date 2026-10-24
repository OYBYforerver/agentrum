"""User management (platform admin only in the MVP)."""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit
from agentrum.auth import security
from agentrum.auth.deps import client_ip, require_platform_admin
from agentrum.db import models
from agentrum.db.engine import get_session

router = APIRouter()

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")


class UserCreateIn(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class UserPatchIn(BaseModel):
    display_name: str | None = None
    disabled: bool | None = None
    is_platform_admin: bool | None = None
    new_password: str | None = None  # admin-initiated password reset


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    is_platform_admin: bool
    disabled: bool = False


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateIn,
    request: Request,
    _admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    if not _USERNAME_RE.match(body.username or ""):
        raise HTTPException(
            status_code=400,
            detail="username must be 1-63 chars of letters, digits, '.', '_' or '-'",
        )
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
    await audit.record(
        session, actor=_admin, action="user.create",
        detail={"user": body.username}, source_ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(user)
    return UserOut(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
    )


@router.patch("/{username}", response_model=UserOut)
async def patch_user(
    username: str,
    body: UserPatchIn,
    request: Request,
    admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = (
        await session.execute(select(models.User).where(models.User.username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.id == admin.id and body.disabled is True:
        raise HTTPException(status_code=400, detail="cannot disable your own account")

    # Keep at least one enabled platform admin: removing the flag from, or
    # disabling, the last one would lock the management plane.
    loses_admin = (
        (body.is_platform_admin is False and user.is_platform_admin)
        or (body.disabled is True and user.is_platform_admin)
    )
    if loses_admin:
        other_admins = (
            await session.execute(
                select(func.count())
                .select_from(models.User)
                .where(
                    models.User.is_platform_admin.is_(True),
                    models.User.disabled_at.is_(None),
                    models.User.id != user.id,
                )
            )
        ).scalar_one()
        if other_admins == 0:
            raise HTTPException(status_code=400, detail="cannot demote or disable the last platform admin")

    if body.new_password is not None:
        if len(body.new_password) < 8:
            raise HTTPException(status_code=400, detail="password must be at least 8 chars")
        user.password_hash = security.hash_password(body.new_password)
        # An admin reset must cut off sessions issued before the reset.
        user.password_changed_at = datetime.now(UTC)
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.is_platform_admin is not None:
        user.is_platform_admin = body.is_platform_admin
    if body.disabled is not None:
        if body.disabled:
            user.disabled_at = datetime.now(UTC)
            # Disabled users lose API access immediately.
            await session.execute(
                update(models.ApiToken)
                .where(models.ApiToken.user_id == user.id, models.ApiToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
        else:
            user.disabled_at = None
    await audit.record(
        session, actor=admin, action="user.update", detail={
            "user": username,
            "disabled": body.disabled,
            "is_platform_admin": body.is_platform_admin,
        },
        source_ip=request.client.host if request.client else None,
    )
    await session.commit()
    await session.refresh(user)
    return _to_out(user)


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: models.User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UserOut]:
    rows = (
        await session.execute(select(models.User).order_by(models.User.username))
    ).scalars().all()
    return [_to_out(u) for u in rows]


def _to_out(u: models.User) -> UserOut:
    return UserOut(
        id=str(u.id),
        username=u.username,
        display_name=u.display_name,
        is_platform_admin=u.is_platform_admin,
        disabled=u.disabled_at is not None,
    )
