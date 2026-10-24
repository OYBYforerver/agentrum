"""Background dispatcher: drains the notification outbox to configured
channels (Feishu custom bot and/or a generic HMAC-signed webhook).

Delivery is two-phase so slow webhooks never hold row locks or a transaction:
a short transaction *claims* a batch (status=processing + lease), delivery
happens outside any transaction, and each result is written back in its own
short transaction. Crashes are recovered by lease expiry — delivery is
at-least-once, so webhook consumers should tolerate (keyed) duplicates.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import and_, or_, select, update

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.notifications")

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 30
BATCH_SIZE = 50
# How long a claimed batch stays ours if we crash before writing back.
LEASE_SECONDS = 300
# Requeue delay when no delivery channel is configured yet (instead of
# permanently skipping: channels are often configured after startup).
NO_CHANNEL_RETRY_SECONDS = 15 * 60

_http: httpx.AsyncClient | None = None


def feishu_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _format_text(payload: dict) -> str:
    if payload.get("event") == "resource.deleted":
        return (
            f"🗑️ Agentrum: {payload['kind']} "
            f"{payload['namespace']}/{payload['name']} 已删除"
            f"，订阅团队: {payload.get('subscriber_team', '-')}"
        )
    if payload.get("event") == "resource.deprecated":
        successor = f"，替代: {payload['successor']}" if payload.get("successor") else ""
        reason = f"（{payload['reason']}）" if payload.get("reason") else ""
        return (
            f"⏳ Agentrum: {payload['kind']} "
            f"{payload['namespace']}/{payload['name']} 已标记弃用{reason}{successor}"
            f"，订阅团队: {payload.get('subscriber_team', '-')}"
        )
    tag = f" ({payload['tag']})" if payload.get("tag") else ""
    return (
        f"📢 Agentrum: {payload['kind']} "
        f"{payload['namespace']}/{payload['name']} 发布新版本 "
        f"v{payload['version']}{tag}"
        f"，订阅团队: {payload.get('subscriber_team', '-')}"
    )


def _webhook_signature(secret: str, payload: dict) -> str:
    """HMAC over canonical JSON so receivers can verify without reimplementing
    Python dict repr."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


async def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=10)
    return _http


async def _deliver(client: httpx.AsyncClient, payload: dict) -> None:
    """Deliver to every configured channel. Raises on channel failure."""
    settings = get_settings()
    text = _format_text(payload)
    if settings.feishu_webhook_url:
        body: dict = {"msg_type": "text", "content": {"text": text}}
        if settings.feishu_webhook_secret:
            timestamp = int(time.time())
            body["timestamp"] = str(timestamp)
            body["sign"] = feishu_sign(settings.feishu_webhook_secret, timestamp)
        resp = await client.post(settings.feishu_webhook_url, json=body)
        resp.raise_for_status()
        if resp.json().get("code") not in (0, None):
            raise RuntimeError(f"feishu rejected: {resp.json()}")
    if settings.notification_webhook_url:
        headers = {}
        if settings.notification_webhook_secret:
            headers["X-Agentrum-Signature"] = _webhook_signature(
                settings.notification_webhook_secret, payload
            )
        resp = await client.post(settings.notification_webhook_url, json=payload, headers=headers)
        resp.raise_for_status()


async def _claim_batch() -> list[models.NotificationOutbox]:
    """Short transaction: lock and mark a due batch as ours (processing)."""
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(models.NotificationOutbox)
                .where(
                    or_(
                        and_(
                            models.NotificationOutbox.status == "pending",
                            models.NotificationOutbox.next_attempt_at <= now,
                        ),
                        # Expired lease: a previous claimant died mid-flight.
                        and_(
                            models.NotificationOutbox.status == "processing",
                            models.NotificationOutbox.next_attempt_at <= now,
                        ),
                    )
                )
                .order_by(models.NotificationOutbox.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not rows:
            return []
        await session.execute(
            update(models.NotificationOutbox)
            .where(models.NotificationOutbox.id.in_([r.id for r in rows]))
            .values(status="processing", next_attempt_at=now + timedelta(seconds=LEASE_SECONDS))
        )
        await session.commit()
        return rows


async def _write_back(row_id: int, *, delivered: bool, error: str | None) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        row = await session.get(models.NotificationOutbox, row_id)
        if row is None:  # pruned between claim and delivery
            return
        row.attempts += 1
        if delivered:
            row.status = "sent"
            row.last_error = None
        else:
            row.last_error = (error or "delivery failed")[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                logger.error("notification %s failed permanently: %s", row_id, error)
            else:
                row.next_attempt_at = now + timedelta(
                    seconds=BASE_BACKOFF_SECONDS * 2 ** (row.attempts - 1)
                )
        await session.commit()


async def tick() -> int:
    """Deliver a batch of due notifications. Returns the number delivered."""
    rows = await _claim_batch()
    if not rows:
        return 0

    settings = get_settings()
    no_channels = not (settings.feishu_webhook_url or settings.notification_webhook_url)

    if no_channels:
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            await session.execute(
                update(models.NotificationOutbox)
                .where(models.NotificationOutbox.id.in_([r.id for r in rows]))
                .values(status="pending", next_attempt_at=now + timedelta(seconds=NO_CHANNEL_RETRY_SECONDS))
            )
            await session.commit()
        return 0

    client = await _client()
    delivered = 0
    for row in rows:
        try:
            await _deliver(client, row.payload)
        except Exception as exc:  # noqa: BLE001 - delivery errors are expected
            logger.warning("notification %s delivery failed: %s", row.id, exc)
            await _write_back(row.id, delivered=False, error=str(exc))
        else:
            delivered += 1
            await _write_back(row.id, delivered=True, error=None)
    return delivered


async def run_forever() -> None:
    interval = get_settings().notification_interval_seconds
    if interval <= 0:
        logger.info("notification dispatcher disabled (interval=0)")
        return
    logger.info("notification dispatcher started (interval=%ss)", interval)
    while True:
        try:
            n = await tick()
            if n:
                logger.info("delivered %s notifications", n)
        except Exception:
            logger.exception("notification tick failed")
        await asyncio.sleep(max(interval, 1))


def start_dispatcher() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_dispatcher(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
