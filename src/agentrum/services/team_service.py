"""Team and namespace management."""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit, errors
from agentrum.db import models

TEAM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")

# Ordered from most to least privileged.
ROLES = (models.ROLE_ADMIN, models.ROLE_PUBLISHER, models.ROLE_MEMBER)


async def get_team(session: AsyncSession, name: str) -> models.Team:
    team = (
        await session.execute(select(models.Team).where(models.Team.name == name))
    ).scalar_one_or_none()
    if team is None:
        raise errors.NotFoundError(f"team {name!r} not found")
    return team


async def get_team_role(session: AsyncSession, user_id: uuid.UUID, team_id: uuid.UUID) -> str | None:
    row = await session.get(models.TeamMember, (team_id, user_id))
    return row.role if row else None


async def get_user_team_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = (
        await session.execute(
            select(models.TeamMember.team_id).where(models.TeamMember.user_id == user_id)
        )
    ).scalars().all()
    return list(rows)


async def require_member(
    session: AsyncSession, actor: models.User, team: models.Team, minimum: str | None = None
) -> str:
    """Return the actor's effective role in `team`.

    Platform admins act as team admins. With `minimum`, require at least that
    role (e.g. "publisher" accepts admin and publisher, rejects member).
    """
    if actor.is_platform_admin:
        return models.ROLE_ADMIN
    role = await get_team_role(session, actor.id, team.id)
    if role is None:
        raise errors.PermissionDeniedError(f"you are not a member of team {team.name!r}")
    if minimum is not None and ROLES.index(role) > ROLES.index(minimum):
        raise errors.PermissionDeniedError(f"role {minimum!r} or higher required in team {team.name!r}")
    return role


async def usernames(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = list({i for i in ids if i is not None})
    if not ids:
        return {}
    rows = (
        await session.execute(select(models.User.id, models.User.username).where(models.User.id.in_(ids)))
    ).all()
    return {row[0]: row[1] for row in rows}


async def create_team(
    session: AsyncSession, actor: models.User, name: str, display_name: str | None,
    description: str | None, source_ip: str | None = None,
) -> models.Team:
    if not actor.is_platform_admin:
        raise errors.PermissionDeniedError("only platform admins can create teams")
    if not TEAM_NAME_RE.match(name or ""):
        raise errors.ValidationError("team name must be 2-63 chars of lowercase letters, digits or '-'")
    existing = (
        await session.execute(select(models.Team).where(models.Team.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        raise errors.ConflictError(f"team {name!r} already exists")

    team = models.Team(name=name, display_name=display_name, description=description)
    session.add(team)
    await session.flush()
    # Every team starts with a namespace of the same name and its creator as admin.
    session.add(models.Namespace(name=name, team_id=team.id))
    session.add(models.TeamMember(team_id=team.id, user_id=actor.id, role=models.ROLE_ADMIN))
    await audit.record(session, actor=actor, action="team.create", detail={"team": name}, source_ip=source_ip)
    await session.commit()
    await session.refresh(team)
    return team


async def list_teams(session: AsyncSession, actor: models.User) -> list[tuple[models.Team, str | None]]:
    rows = (
        await session.execute(
            select(models.Team, models.TeamMember.role)
            .outerjoin(
                models.TeamMember,
                (models.TeamMember.team_id == models.Team.id)
                & (models.TeamMember.user_id == actor.id),
            )
            .order_by(models.Team.name)
        )
    ).all()
    return [(team, models.ROLE_ADMIN if actor.is_platform_admin else role) for team, role in rows]


async def list_members(session: AsyncSession, actor: models.User, team: models.Team):
    await require_member(session, actor, team)
    rows = (
        await session.execute(
            select(models.User, models.TeamMember.role)
            .join(models.TeamMember, models.TeamMember.user_id == models.User.id)
            .where(models.TeamMember.team_id == team.id)
            .order_by(models.User.username)
        )
    ).all()
    return rows


async def add_member(
    session: AsyncSession, actor: models.User, team: models.Team, username: str, role: str,
    source_ip: str | None = None,
) -> models.User:
    await require_member(session, actor, team, minimum=models.ROLE_ADMIN)
    if role not in ROLES:
        raise errors.ValidationError(f"role must be one of {list(ROLES)}")
    user = (
        await session.execute(select(models.User).where(models.User.username == username))
    ).scalar_one_or_none()
    if user is None:
        raise errors.NotFoundError(f"user {username!r} not found")

    member = await session.get(models.TeamMember, (team.id, user.id))
    if member is not None:
        member.role = role
    else:
        session.add(models.TeamMember(team_id=team.id, user_id=user.id, role=role))
    await audit.record(
        session, actor=actor, action="team.member.add", detail={"team": team.name, "member": username, "role": role},
        source_ip=source_ip,
    )
    await session.commit()
    return user


async def update_member(
    session: AsyncSession, actor: models.User, team: models.Team, username: str, role: str,
    source_ip: str | None = None,
) -> None:
    await require_member(session, actor, team, minimum=models.ROLE_ADMIN)
    if role not in ROLES:
        raise errors.ValidationError(f"role must be one of {list(ROLES)}")
    user = (
        await session.execute(select(models.User).where(models.User.username == username))
    ).scalar_one_or_none()
    if user is None:
        raise errors.NotFoundError(f"user {username!r} not found")
    member = await session.get(models.TeamMember, (team.id, user.id))
    if member is None:
        raise errors.NotFoundError(f"user {username!r} is not a member of team {team.name!r}")
    if member.role == models.ROLE_ADMIN and role != models.ROLE_ADMIN:
        await _ensure_not_last_admin(session, team)
    member.role = role
    await audit.record(
        session, actor=actor, action="team.member.update", detail={"team": team.name, "member": username, "role": role},
        source_ip=source_ip,
    )
    await session.commit()


async def remove_member(
    session: AsyncSession, actor: models.User, team: models.Team, username: str,
    source_ip: str | None = None,
) -> None:
    await require_member(session, actor, team, minimum=models.ROLE_ADMIN)
    user = (
        await session.execute(select(models.User).where(models.User.username == username))
    ).scalar_one_or_none()
    if user is None:
        raise errors.NotFoundError(f"user {username!r} not found")
    member = await session.get(models.TeamMember, (team.id, user.id))
    if member is None:
        raise errors.NotFoundError(f"user {username!r} is not a member of team {team.name!r}")
    if member.role == models.ROLE_ADMIN:
        await _ensure_not_last_admin(session, team)
    await session.delete(member)
    await audit.record(
        session, actor=actor, action="team.member.remove", detail={"team": team.name, "member": username},
        source_ip=source_ip,
    )
    await session.commit()


async def _ensure_not_last_admin(session: AsyncSession, team: models.Team) -> None:
    admins = (
        await session.execute(
            select(func.count())
            .select_from(models.TeamMember)
            .where(
                models.TeamMember.team_id == team.id,
                models.TeamMember.role == models.ROLE_ADMIN,
            )
        )
    ).scalar_one()
    if admins <= 1:
        raise errors.ConflictError("cannot remove or demote the last admin of a team")
