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


@router.get("/{team_name}/stats", response_model=dict)
async def team_stats(
    team_name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Project overview metrics for the console landing page."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, user, team)

    by_kind = dict(
        (
            await session.execute(
                select(models.Resource.kind, func.count())
                .where(
                    models.Resource.namespace == team.name,
                    models.Resource.deleted_at.is_(None),
                )
                .group_by(models.Resource.kind)
            )
        ).all()
    )
    published_7d = (
        await session.execute(
            select(func.count())
            .select_from(models.ResourceVersion)
            .join(models.Resource, models.Resource.id == models.ResourceVersion.resource_id)
            .where(
                models.Resource.namespace == team.name,
                models.ResourceVersion.created_at >= datetime.now(UTC) - timedelta(days=7),
            )
        )
    ).scalar_one()
    subscriber_rows = (
        await session.execute(
            select(func.count(func.distinct(models.Subscription.subscriber_team_id)))
            .join(models.Namespace, models.Namespace.name == models.Subscription.namespace)
            .where(models.Namespace.team_id == team.id, models.Subscription.status == models.SUB_ACTIVE)
        )
    ).scalar_one()
    pending = (
        await session.execute(
            select(func.count())
            .select_from(models.Subscription)
            .join(models.Namespace, models.Namespace.name == models.Subscription.namespace)
            .where(models.Namespace.team_id == team.id, models.Subscription.status == models.SUB_PENDING)
        )
    ).scalar_one()
    return {
        "resources_by_kind": by_kind,
        "total_resources": sum(by_kind.values()),
        "published_last_7d": published_7d,
        "subscribers": subscriber_rows,
        "pending_approvals": pending,
    }


@router.get("/{team_name}/consumers", response_model=list[dict])
async def list_consumers(
    team_name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Consumer graph: teams actively subscribing to this team's content
    (impact analysis before deprecating anything)."""
    from agentrum.services import notification_service

    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, user, team)
    rows = await notification_service.list_consumers(session, team_name)
    return [
        {
            "subscriber_team": subscriber,
            "kind": sub.kind,
            "namespace": sub.namespace,
            "name": sub.name,
            "since": sub.created_at.isoformat(),
        }
        for subscriber, sub in rows
    ]


# Errors are surfaced as machine-readable {code, detail} envelopes here to
# keep routers thin. Codes are stable identifiers for CLI/UI localization.
def install_error_handlers(app) -> None:  # pragma: no cover
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(errors.AgentrumError)
    async def _domain(request: Request, exc: errors.AgentrumError):
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "detail": exc.detail, **exc.context},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": f"http_{exc.status_code}", "detail": str(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_request", "detail": f"{loc}: {first.get('msg', 'invalid')}"},
        )
