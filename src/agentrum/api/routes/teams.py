from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import errors
from agentrum.auth.deps import get_current_user
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.schemas.team import MemberAddIn, MemberOut, MemberUpdateIn, TeamCreateIn, TeamOut
from agentrum.services import team_service

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(
    body: TeamCreateIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TeamOut:
    team = await team_service.create_team(
        session, user, body.name, body.display_name, body.description,
        source_ip=_client_ip(request),
    )
    return TeamOut(
        id=str(team.id), name=team.name, display_name=team.display_name,
        description=team.description, my_role="admin",
    )


@router.get("", response_model=list[TeamOut])
async def list_teams(
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TeamOut]:
    rows = await team_service.list_teams(session, user)
    return [
        TeamOut(
            id=str(team.id), name=team.name, display_name=team.display_name,
            description=team.description, my_role=role,
        )
        for team, role in rows
    ]


@router.get("/{team_name}/members", response_model=list[MemberOut])
async def list_members(
    team_name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MemberOut]:
    team = await team_service.get_team(session, team_name)
    rows = await team_service.list_members(session, user, team)
    return [
        MemberOut(username=u.username, display_name=u.display_name, role=role) for u, role in rows
    ]


@router.post("/{team_name}/members", response_model=MemberOut, status_code=201)
async def add_member(
    team_name: str,
    body: MemberAddIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MemberOut:
    team = await team_service.get_team(session, team_name)
    member = await team_service.add_member(
        session, user, team, body.username, body.role, source_ip=_client_ip(request)
    )
    role = await team_service.get_team_role(session, member.id, team.id)
    return MemberOut(username=member.username, display_name=member.display_name, role=role)


@router.patch("/{team_name}/members/{username}", response_model=MemberOut)
async def update_member(
    team_name: str,
    username: str,
    body: MemberUpdateIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MemberOut:
    team = await team_service.get_team(session, team_name)
    await team_service.update_member(
        session, user, team, username, body.role, source_ip=_client_ip(request)
    )
    target = (
        await session.execute(select(models.User).where(models.User.username == username))
    ).scalar_one()
    role = await team_service.get_team_role(session, target.id, team.id)
    return MemberOut(username=target.username, display_name=target.display_name, role=role)


@router.delete("/{team_name}/members/{username}", status_code=204)
async def remove_member(
    team_name: str,
    username: str,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    team = await team_service.get_team(session, team_name)
    await team_service.remove_member(session, user, team, username, source_ip=_client_ip(request))


# Domain errors are surfaced as clean 4xx responses here to keep routers thin.
def install_error_handlers(app) -> None:  # pragma: no cover
    from fastapi.responses import JSONResponse

    status_map = {
        errors.NotFoundError: 404,
        errors.PermissionDeniedError: 403,
        errors.ConflictError: 409,
        errors.ValidationError: 400,
        errors.AgentrumError: 400,
    }

    @app.exception_handler(errors.AgentrumError)
    async def _handle(request: Request, exc: errors.AgentrumError):
        code = status_map.get(type(exc), 400)
        return JSONResponse(status_code=code, content={"detail": str(exc)})
