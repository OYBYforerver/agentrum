"""Transactional-outbox notifications for subscription events."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.db import models


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

    for sub, team_name in rows:
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
    return len(rows)
