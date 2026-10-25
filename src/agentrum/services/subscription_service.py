"""Cross-team subscriptions: request, approve, revoke."""

import uuid

from sqlalchemy import select, update
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
    if kind == "Prompt":
        raise errors.ValidationError(
            "prompts are project-private and cannot be subscribed across projects"
        )
    if kind == "Secret":
        raise errors.ValidationError(
            "secrets cannot be subscribed across projects; reference them from "
            "a deployment in their own namespace instead"
        )
    ns = await session.get(models.Namespace, data.namespace)
    if ns is None:
        raise errors.NotFoundError(f"namespace {data.namespace!r} not found")
    if ns.team_id == team.id:
        raise errors.ConflictError("cannot subscribe to your own team's namespace")

    target: models.Resource | None = None
    if data.name != "*":
        target = await resource_service._get_resource(session, kind, data.namespace, data.name)
        if target is None:
            raise errors.NotFoundError(f"{kind.lower()}/{data.namespace}/{data.name} not found")

    # Restricted resources require approval by the owning team; everything
    # else activates immediately. Wildcard subscriptions activate immediately
    # but only ever grant INTERNAL resources (see resource_service grants).
    status = (
        models.SUB_PENDING
        if target is not None and target.visibility == models.VISIBILITY_RESTRICTED
        else models.SUB_ACTIVE
    )

    # A previously rejected/revoked subscription row blocks re-creation via
    # the unique constraint; revive it instead of dead-locking the target.
    existing = (
        await session.execute(
            select(models.Subscription).where(
                models.Subscription.subscriber_team_id == team.id,
                models.Subscription.kind == kind,
                models.Subscription.namespace == data.namespace,
                models.Subscription.name == data.name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status != models.SUB_REVOKED:
            raise errors.ConflictError("subscription already exists for this target")
        existing.status = status
        existing.events = data.events or ["new_version"]
        existing.requested_by = actor.id
        existing.approved_by = None
        await audit.record(
            session, actor=actor, action="subscription.request",
            kind=kind, namespace=data.namespace, name=data.name,
            detail={"team": team_name, "status": status, "revived": True},
            source_ip=source_ip,
        )
        await session.commit()
        await session.refresh(existing)
        return existing

    sub = models.Subscription(
        subscriber_team_id=team.id,
        kind=kind,
        namespace=data.namespace,
        name=data.name,
        events=data.events or ["new_version"],
        pinned_tag=data.pinned_tag,
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
    ns = await session.get(models.Namespace, sub.namespace)
    if ns is None:
        raise errors.NotFoundError(f"namespace {sub.namespace!r} no longer exists")
    if not actor.is_platform_admin:
        role = await team_service.get_team_role(session, actor.id, ns.team_id)
        if role != models.ROLE_ADMIN:
            raise errors.PermissionDeniedError(
                "only an admin of the team that owns the target namespace can decide"
            )
    # Conditional transition: concurrent approve/reject decisions cannot both
    # win — the second one observes the status already moved on.
    result = await session.execute(
        update(models.Subscription)
        .where(
            models.Subscription.id == sub.id,
            models.Subscription.status == models.SUB_PENDING,
        )
        .values(
            status=models.SUB_ACTIVE if approved else models.SUB_REVOKED,
            approved_by=actor.id,
        )
    )
    if result.rowcount == 0:
        raise errors.ConflictError(
            f"subscription is {sub.status!r}, not pending approval"
        )
    await audit.record(
        session, actor=actor, action="subscription.approve" if approved else "subscription.reject",
        kind=sub.kind, namespace=sub.namespace, name=sub.name,
        detail={"subscription": str(sub.id)}, source_ip=source_ip,
    )
    await session.commit()
    await session.refresh(sub)
    return sub


async def set_pin(
    session: AsyncSession, actor: models.User, sub_id: uuid.UUID,
    pinned_tag: str | None, source_ip: str | None = None,
) -> models.Subscription:
    """Set or clear a subscription's version pin. Consumption-level config:
    any member of the *subscriber* team may change it."""
    sub = await _get_sub(session, sub_id)
    if not actor.is_platform_admin:
        team = await session.get(models.Team, sub.subscriber_team_id)
        if team is None:
            raise errors.NotFoundError("subscriber team no longer exists")
        await team_service.require_member(session, actor, team)
    if pinned_tag is not None:
        pinned_tag = pinned_tag.strip()
        if not pinned_tag or len(pinned_tag) > 63:
            raise errors.ValidationError("pinned_tag must be 1-63 characters")
    sub.pinned_tag = pinned_tag or None
    await audit.record(
        session, actor=actor, action="subscription.pin",
        kind=sub.kind, namespace=sub.namespace, name=sub.name,
        detail={"pinned_tag": sub.pinned_tag}, source_ip=source_ip,
    )
    await session.commit()
    await session.refresh(sub)
    return sub


async def revoke(
    session: AsyncSession, actor: models.User, sub_id: uuid.UUID, source_ip: str | None = None
) -> models.Subscription:
    """Revoke a subscription. Allowed for: the subscriber team, the team that
    owns the target namespace (grant revocation), or a platform admin."""
    sub = await _get_sub(session, sub_id)

    allowed = actor.is_platform_admin
    revoked_by = "subscriber"
    if not allowed:
        subscriber_team = await session.get(models.Team, sub.subscriber_team_id)
        if subscriber_team is not None:
            try:
                await team_service.require_member(session, actor, subscriber_team)
                allowed = True
            except errors.PermissionDeniedError:
                allowed = False
    if not allowed:
        ns = await session.get(models.Namespace, sub.namespace)
        if ns is not None:
            role = await team_service.get_team_role(session, actor.id, ns.team_id)
            if role == models.ROLE_ADMIN:
                allowed = True
                revoked_by = "owner"
    if not allowed:
        raise errors.PermissionDeniedError(
            "only the subscriber or the target project's admin can revoke"
        )

    result = await session.execute(
        update(models.Subscription)
        .where(
            models.Subscription.id == sub.id,
            models.Subscription.status != models.SUB_REVOKED,
        )
        .values(status=models.SUB_REVOKED)
    )
    if result.rowcount == 0:
        raise errors.ConflictError("subscription already revoked")
    await audit.record(
        session, actor=actor, action="subscription.revoke", kind=sub.kind,
        namespace=sub.namespace, name=sub.name, detail={"subscription": str(sub.id), "by": revoked_by},
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
