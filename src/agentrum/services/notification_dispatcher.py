"""Background dispatcher: drains the notification outbox to configured
channels (Feishu custom bot and/or a generic HMAC-signed webhook)."""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.notifications")

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 30


def feishu_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _format_text(payload: dict) -> str:
    tag = f" ({payload['tag']})" if payload.get("tag") else ""
    return (
        f"📢 Agentrum: {payload['kind']} "
        f"{payload['namespace']}/{payload['name']} 发布新版本 "
        f"v{payload['version']}{tag}"
        f"，订阅团队: {payload.get('subscriber_team', '-')}"
    )


async def _deliver(payload: dict) -> None:
    """Deliver to every configured channel. Raises on channel failure."""
    settings = get_settings()
    text = _format_text(payload)
    async with httpx.AsyncClient(timeout=10) as client:
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
                sig = hmac.new(
                    settings.notification_webhook_secret.encode(),
                    msg=repr(payload).encode(),
                    digestmod=hashlib.sha256,
                ).hexdigest()
                headers["X-Agentrum-Signature"] = sig
            resp = await client.post(
                settings.notification_webhook_url, json=payload, headers=headers
            )
            resp.raise_for_status()


async def tick() -> int:
    """Deliver a batch of due notifications. Returns the number processed."""
    now = datetime.now(UTC)
    delivered = 0
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(models.NotificationOutbox)
                .where(
                    models.NotificationOutbox.status == "pending",
                    models.NotificationOutbox.next_attempt_at <= now,
                )
                .order_by(models.NotificationOutbox.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not rows:
            return 0

        settings = get_settings()
        no_channels = not (settings.feishu_webhook_url or settings.notification_webhook_url)

        for row in rows:
            if no_channels:
                row.status = "skipped"
                continue
            try:
                await _deliver(row.payload)
            except Exception as exc:  # noqa: BLE001 - delivery errors are expected
                row.attempts += 1
                row.last_error = str(exc)[:500]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    logger.error("notification %s failed permanently: %s", row.id, exc)
                else:
                    row.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=BASE_BACKOFF_SECONDS * 2 ** (row.attempts - 1)
                    )
            else:
                row.attempts += 1
                row.status = "sent"
                row.last_error = None
                delivered += 1
        await session.commit()
    return delivered


async def run_forever() -> None:
    interval = get_settings().notification_interval_seconds
    logger.info("notification dispatcher started (interval=%ss)", interval)
    while True:
        try:
            n = await tick()
            if n:
                logger.info("delivered %s notifications", n)
        except Exception:
            logger.exception("notification tick failed")
        await asyncio.sleep(interval)


def start_dispatcher() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_dispatcher(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
