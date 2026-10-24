"""Retention maintenance: prune audit log and delivered notifications."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.maintenance")

# Unbounded single-statement DELETEs bloat tables and hold long transactions
# on large retention backlogs; chew through them in batches instead.
_BATCH_SIZE = 5000


async def _batched_delete(session, model, stmt_filter, id_column) -> int:  # type: ignore[no-untyped-def]
    deleted = 0
    while True:
        result = await session.execute(
            sa_delete(model).where(
                id_column.in_(
                    select(id_column).where(stmt_filter).limit(_BATCH_SIZE).scalar_subquery()
                )
            )
        )
        count = result.rowcount or 0
        deleted += count
        await session.commit()
        if count < _BATCH_SIZE:
            return deleted


async def prune_once() -> dict[str, int]:  # pragma: no cover - exercised via wiring
    settings = get_settings()
    now = datetime.now(UTC)
    summary: dict[str, int] = {}
    async with SessionLocal() as session:
        audit_cutoff = now - timedelta(days=settings.audit_retention_days)
        summary["audit_deleted"] = await _batched_delete(
            session, models.AuditLog, models.AuditLog.occurred_at < audit_cutoff, models.AuditLog.id
        )

        outbox_cutoff = now - timedelta(days=settings.notification_retention_days)
        summary["outbox_deleted"] = await _batched_delete(
            session,
            models.NotificationOutbox,
            models.NotificationOutbox.status.in_(["sent", "failed", "skipped"])
            & (models.NotificationOutbox.created_at < outbox_cutoff),
            models.NotificationOutbox.id,
        )
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
