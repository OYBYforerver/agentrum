"""Retention maintenance: prune audit log and delivered notifications."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.maintenance")


async def prune_once() -> dict[str, int]:  # pragma: no cover - exercised via wiring
    settings = get_settings()
    now = datetime.now(UTC)
    summary: dict[str, int] = {}
    async with SessionLocal() as session:
        audit_cutoff = now - timedelta(days=settings.audit_retention_days)
        result = await session.execute(
            sa_delete(models.AuditLog).where(models.AuditLog.occurred_at < audit_cutoff)
        )
        summary["audit_deleted"] = result.rowcount or 0

        outbox_cutoff = now - timedelta(days=settings.notification_retention_days)
        result = await session.execute(
            sa_delete(models.NotificationOutbox).where(
                models.NotificationOutbox.status.in_(["sent", "failed", "skipped"]),
                models.NotificationOutbox.created_at < outbox_cutoff,
            )
        )
        summary["outbox_deleted"] = result.rowcount or 0
        await session.commit()
    if any(summary.values()):
        logger.info("retention prune: %s", summary)
    return summary


async def run_forever() -> None:  # pragma: no cover - background loop
    while True:
        try:
            await prune_once()
        except Exception:
            logger.exception("maintenance tick failed")
        await asyncio.sleep(24 * 3600)


def start_maintenance() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_maintenance(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
