"""Health probes for published MCPServer endpoints.

Any HTTP response from the endpoint means the server is up (MCP endpoints
reject plain GETs with 405 — that still proves liveness); connection errors
mark the resource NotReady.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.probe")


def _condition(ok: bool, message: str) -> dict:
    return {
        "type": "Ready",
        "status": "True" if ok else "False",
        "message": message,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


async def probe_once(session) -> int:  # pragma: no cover - exercised via service wiring
    rows = (
        await session.execute(
            select(models.Resource)
            .where(
                models.Resource.kind == "MCPServer",
                models.Resource.deleted_at.is_(None),
            )
            .limit(200)
        )
    ).scalars().all()
    if not rows:
        return 0

    latest: dict = {}
    ids = [r.id for r in rows]
    versions = (
        await session.execute(
            select(models.ResourceVersion)
            .where(models.ResourceVersion.resource_id.in_(ids))
            .order_by(models.ResourceVersion.version.desc())
        )
    ).scalars().all()
    for rv in versions:
        latest.setdefault(rv.resource_id, rv)

    async with httpx.AsyncClient(timeout=5, verify=False) as http:
        for resource in rows:
            rv = latest.get(resource.id)
            endpoint = (rv.spec or {}).get("endpoint") if rv else None
            if not endpoint:
                continue
            try:
                resp = await http.get(str(endpoint))
                condition = _condition(resp.status_code < 500, f"HTTP {resp.status_code}")
            except httpx.HTTPError as exc:
                condition = _condition(False, f"unreachable: {exc.__class__.__name__}")
            new_status = {"conditions": [condition]}
            if (resource.status or {}).get("conditions") != new_status["conditions"]:
                resource.status = new_status
    await session.commit()
    return len(rows)


async def run_forever() -> None:  # pragma: no cover - background loop
    interval = get_settings().probe_interval_seconds
    logger.info("endpoint prober started (interval=%ss)", interval)
    while True:
        try:
            async with SessionLocal() as session:
                await probe_once(session)
        except Exception:
            logger.exception("probe tick failed")
        await asyncio.sleep(interval)


def start_prober() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_prober(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
