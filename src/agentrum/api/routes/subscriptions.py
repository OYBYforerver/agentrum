import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import errors
from agentrum.auth.deps import client_ip, get_current_user
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.schemas.subscription import (
    SubscriptionCreateIn,
    SubscriptionListOut,
    SubscriptionOut,
    SubscriptionPinIn,
)
from agentrum.services import subscription_service, team_service

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return client_ip(request)


def _uuid_or_404(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise errors.NotFoundError("subscription not found") from None


async def _serialize(session: AsyncSession, subs: list[models.Subscription]) -> list[SubscriptionOut]:
    team_rows = (
        await session.execute(
            select(models.Team).where(models.Team.id.in_({s.subscriber_team_id for s in subs}))
        )
    ).scalars().all() if subs else []
    team_names = {t.id: t.name for t in team_rows}
    user_names = await team_service.usernames(
        session, [s.requested_by for s in subs] + [s.approved_by for s in subs]
    )
    return [
        SubscriptionOut(
            id=str(s.id),
            subscriber_team=team_names.get(s.subscriber_team_id, str(s.subscriber_team_id)),
            kind=s.kind,
            namespace=s.namespace,
            name=s.name,
            events=s.events or [],
            pinned_tag=s.pinned_tag,
            status=s.status,
            requested_by=user_names.get(s.requested_by, str(s.requested_by)),
            approved_by=user_names.get(s.approved_by) if s.approved_by else None,
            created_at=s.created_at,
        )
        for s in subs
    ]


@router.post("/v1/teams/{team_name}/subscriptions", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    team_name: str,
    body: SubscriptionCreateIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    sub = await subscription_service.create(
        session, user, team_name, body, source_ip=_client_ip(request)
    )
    return (await _serialize(session, [sub]))[0]


@router.get("/v1/teams/{team_name}/subscriptions", response_model=SubscriptionListOut)
async def list_subscriptions(
    team_name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionListOut:
    subs = await subscription_service.list_for_team(session, user, team_name)
    return SubscriptionListOut(items=await _serialize(session, subs))


@router.get("/v1/teams/{team_name}/subscriptions/pending", response_model=SubscriptionListOut)
async def list_pending_subscriptions(
    team_name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionListOut:
    subs = await subscription_service.pending_for_team(session, user, team_name)
    return SubscriptionListOut(items=await _serialize(session, subs))


@router.post("/v1/subscriptions/{sub_id}/approve", response_model=SubscriptionOut)
async def approve_subscription(
    sub_id: str,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    sub = await subscription_service.approve(
        session, user, _uuid_or_404(sub_id), approved=True, source_ip=_client_ip(request)
    )
    return (await _serialize(session, [sub]))[0]


@router.post("/v1/subscriptions/{sub_id}/reject", response_model=SubscriptionOut)
async def reject_subscription(
    sub_id: str,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    sub = await subscription_service.approve(
        session, user, _uuid_or_404(sub_id), approved=False, source_ip=_client_ip(request)
    )
    return (await _serialize(session, [sub]))[0]


@router.patch("/v1/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def pin_subscription(
    sub_id: str,
    body: SubscriptionPinIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    """Set (`{"pinned_tag": "v1.2.0"}`) or clear (`{"pinned_tag": null}`) the
    subscription's version lock."""
    sub = await subscription_service.set_pin(
        session, user, _uuid_or_404(sub_id), body.pinned_tag, source_ip=_client_ip(request)
    )
    return (await _serialize(session, [sub]))[0]


@router.delete("/v1/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def revoke_subscription(
    sub_id: str,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    sub = await subscription_service.revoke(
        session, user, _uuid_or_404(sub_id), source_ip=_client_ip(request)
    )
    return (await _serialize(session, [sub]))[0]
