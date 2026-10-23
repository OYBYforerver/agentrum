"""Cross-team subscriptions: request, approve, revoke."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit, errors
from agentrum.db import models
from agentrum.services import resource_service, team_service


async def _get_sub(session: AsyncSession, sub_id: uuid.UUID) -> models.Subscription:
    sub = await session.get(models.Subscription, sub_id)
    if sub is None:
        raise errors.NotFoundError("subscription not found")
    return sub


async def create(
    session: AsyncSession, actor: models.User, team_name: str, data, source_ip: str | None = None
) -> models.Subscription:
    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, actor, team)

    kind = resource_service.normalize_kind(data.kind)
    ns = await session.get(models.Namespace, data.namespace)
    if ns is None:
        raise errors.NotFoundError(f"namespace {data.namespace!r} not found")

    target: models.Resource | None = None
    if data.name != "*":
        target = await resource_service._get_resource(session, kind, data.namespace, data.name)
        if target is None:
            raise errors.NotFoundError(f"{kind.lower()}/{data.namespace}/{data.name} not found")

    if ns.team_id == team.id:
        raise errors.ConflictError("cannot subscribe to your own team's namespace")

    dup = (
        await session.execute(
            select(models.Subscription.id).where(
                models.Subscription.subscriber_team_id == team.id,
                models.Subscription.kind == kind,
                models.Subscription.namespace == data.namespace,
                models.Subscription.name == data.name,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise errors.ConflictError("subscription already exists for this target")

    # Restricted resources require approval by the owning team; everything else
    # activates immediately.
    status = (
        models.SUB_PENDING
        if target is not None and target.visibility == models.VISIBILITY_RESTRICTED
        else models.SUB_ACTIVE
    )
    sub = models.Subscription(
        subscriber_team_id=team.id,
        kind=kind,
        namespace=data.namespace,
        name=data.name,
        events=data.events or ["new_version"],
        status=status,
        requested_by=actor.id,
    )
    session.add(sub)
    await audit.record(
        session, actor=actor, action="subscription.request",
        kind=kind, namespace=data.namespace, name=data.name,
        detail={"team": team_name, "status": status}, source_ip=source_ip,
    )
    await session.commit()
    await session.refresh(sub)
    return sub


async def approve(
    session: AsyncSession, actor: models.User, sub_id: uuid.UUID, approved: bool,
    source_ip: str | None = None,
) -> models.Subscription:
    sub = await _get_sub(session, sub_id)
    if sub.status != models.SUB_PENDING:
        raise errors.ConflictError(f"subscription is {sub.status!r}, not pending approval")
    ns = await session.get(models.Namespace, sub.namespace)
    if ns is None:
        raise errors.NotFoundError(f"namespace {sub.namespace!r} no longer exists")
    if not actor.is_platform_admin:
        role = await team_service.get_team_role(session, actor.id, ns.team_id)
        if role != models.ROLE_ADMIN:
            raise errors.PermissionDeniedError(
                "only an admin of the team that owns the target namespace can decide"
            )
    sub.status = models.SUB_ACTIVE if approved else models.SUB_REVOKED
    sub.approved_by = actor.id
    await audit.record(
        session, actor=actor, action="subscription.approve" if approved else "subscription.reject",
        kind=sub.kind, namespace=sub.namespace, name=sub.name,
        detail={"subscription": str(sub.id)}, source_ip=source_ip,
    )
    await session.commit()
    await session.refresh(sub)
    return sub


async def revoke(
    session: AsyncSession, actor: models.User, sub_id: uuid.UUID, source_ip: str | None = None
) -> models.Subscription:
    sub = await _get_sub(session, sub_id)
    if sub.status == models.SUB_REVOKED:
        raise errors.ConflictError("subscription already revoked")
    subscriber_team = await session.get(models.Team, sub.subscriber_team_id)
    if subscriber_team is not None and not actor.is_platform_admin:
        await team_service.require_member(session, actor, subscriber_team)
    sub.status = models.SUB_REVOKED
    await audit.record(
        session, actor=actor, action="subscription.revoke", kind=sub.kind,
        namespace=sub.namespace, name=sub.name, detail={"subscription": str(sub.id)},
        source_ip=source_ip,
    )
    await session.commit()
    await session.refresh(sub)
    return sub


async def list_for_team(
    session: AsyncSession, actor: models.User, team_name: str
) -> list[models.Subscription]:
    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, actor, team)
    rows = (
        await session.execute(
            select(models.Subscription)
            .where(models.Subscription.subscriber_team_id == team.id)
            .order_by(models.Subscription.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def pending_for_team(
    session: AsyncSession, actor: models.User, team_name: str
) -> list[models.Subscription]:
    """Subscriptions targeting this team's namespaces that await its approval."""
    team = await team_service.get_team(session, team_name)
    await team_service.require_member(session, actor, team)
    rows = (
        await session.execute(
            select(models.Subscription)
            .join(models.Namespace, models.Namespace.name == models.Subscription.namespace)
            .where(models.Namespace.team_id == team.id, models.Subscription.status == models.SUB_PENDING)
            .order_by(models.Subscription.created_at.desc())
        )
    ).scalars().all()
    return list(rows)
