"""Transactional-outbox notifications for subscription events."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.db import models


def _wants_published(sub: models.Subscription) -> bool:
    """Honor the subscriber's declared events. "new_version" is the legacy
    name of "resource.published" (rows created before events were honored)."""
    events = sub.events or ["new_version"]
    return "resource.published" in events or "new_version" in events


def _wants_deleted(sub: models.Subscription) -> bool:
    return "resource.deleted" in (sub.events or [])


async def enqueue_resource_deprecated(
    session: AsyncSession, resource: models.Resource, actor_name: str,
    reason: str | None, successor: str | None,
) -> int:
    """Queue a `resource.deprecated` notice for every active subscriber.

    Unlike published/deleted, deprecation ignores the subscriber's `events`
    preference: it is an impact warning about content they already consume,
    not a catalog event they opted into."""
    rows = (
        await session.execute(
            select(models.Subscription, models.Team.name)
            .join(models.Team, models.Team.id == models.Subscription.subscriber_team_id)
            .where(
                models.Subscription.kind == resource.kind,
                models.Subscription.namespace == resource.namespace,
                models.Subscription.status == models.SUB_ACTIVE,
                models.Subscription.name.in_([resource.name, "*"]),
            )
        )
    ).all()
    queued = 0
    for sub, team_name in rows:
        session.add(
            models.NotificationOutbox(
                event_type="resource.deprecated",
                payload={
                    "event": "resource.deprecated",
                    "kind": resource.kind,
                    "namespace": resource.namespace,
                    "name": resource.name,
                    "subscriber_team": team_name,
                    "deprecated_by": actor_name,
                    "reason": reason,
                    "successor": successor,
                },
            )
        )
        queued += 1
    return queued


async def enqueue_resource_published(
    session: AsyncSession, resource: models.Resource, version: models.ResourceVersion,
    publisher_name: str,
) -> int:
    """Queue a `resource.published` notification for every active subscriber
    of the resource (or its whole namespace). Called inside the publish
    transaction so events never go missing."""
    rows = (
        await session.execute(
            select(models.Subscription, models.Team.name)
            .join(models.Team, models.Team.id == models.Subscription.subscriber_team_id)
            .where(
                models.Subscription.kind == resource.kind,
                models.Subscription.namespace == resource.namespace,
                models.Subscription.status == models.SUB_ACTIVE,
                models.Subscription.name.in_([resource.name, "*"]),
            )
        )
    ).all()

    queued = 0
    for sub, team_name in rows:
        if not _wants_published(sub):
            continue
        session.add(
            models.NotificationOutbox(
                event_type="resource.published",
                payload={
                    "event": "resource.published",
                    "kind": resource.kind,
                    "namespace": resource.namespace,
                    "name": resource.name,
                    "version": version.version,
                    "tag": version.tag,
                    "subscriber_team": team_name,
                    "published_by": publisher_name,
                    "description": resource.description,
                },
            )
        )
        queued += 1
    return queued


async def enqueue_resource_deleted(
    session: AsyncSession, resource: models.Resource, actor_name: str
) -> int:
    """Queue a `resource.deleted` notification for active subscribers —
    deletion cascades to consumers so they can react (impact awareness)."""
    rows = (
        await session.execute(
            select(models.Subscription, models.Team.name)
            .join(models.Team, models.Team.id == models.Subscription.subscriber_team_id)
            .where(
                models.Subscription.kind == resource.kind,
                models.Subscription.namespace == resource.namespace,
                models.Subscription.status == models.SUB_ACTIVE,
                models.Subscription.name.in_([resource.name, "*"]),
            )
        )
    ).all()
    queued = 0
    for sub, team_name in rows:
        if not _wants_deleted(sub):
            continue
        session.add(
            models.NotificationOutbox(
                event_type="resource.deleted",
                payload={
                    "event": "resource.deleted",
                    "kind": resource.kind,
                    "namespace": resource.namespace,
                    "name": resource.name,
                    "subscriber_team": team_name,
                    "deleted_by": actor_name,
                },
            )
        )
        queued += 1
    return queued


async def list_consumers(
    session: AsyncSession, team_name: str
) -> list[tuple[str, models.Subscription]]:
    """Teams that actively subscribe to this team's namespaces (consumer
    graph, used for impact analysis)."""
    from agentrum.services import team_service

    team = await team_service.get_team(session, team_name)
    rows = (
        await session.execute(
            select(models.Subscription, models.Team)
            .select_from(models.Subscription)
            .join(models.Team, models.Team.id == models.Subscription.subscriber_team_id)
            .join(models.Namespace, models.Namespace.name == models.Subscription.namespace)
            .where(
                models.Namespace.team_id == team.id,
                models.Subscription.status == models.SUB_ACTIVE,
            )
            .order_by(models.Team.name)
        )
    ).all()
    return [(t.name, s) for s, t in rows]
