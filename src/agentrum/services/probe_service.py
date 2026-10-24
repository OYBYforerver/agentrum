"""Health probes for published MCPServer endpoints.

streamable-http endpoints get a real MCP `initialize` handshake (so the
condition proves protocol health, and the server's name/version surface in
the status); everything else falls back to the HTTP liveness heuristic (any
response means up — MCP endpoints reject plain GETs with 405).
"""

import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from agentrum import __version__
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.probe")

_PROBE_CONCURRENCY = 10

_MCP_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "agentrum-probe", "version": __version__},
    },
}


def _condition(ok: bool, message: str) -> dict:
    return {
        "type": "Ready",
        "status": "True" if ok else "False",
        "message": message,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _parse_jsonrpc_response(resp: httpx.Response) -> dict | None:
    """Accept both application/json and SSE-framed JSON-RPC responses."""
    body = resp.text
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except ValueError:
                    return None
        return None
    try:
        return resp.json()
    except ValueError:
        return None


async def _probe_streamable_http(
    http: httpx.AsyncClient, endpoint: str, headers: dict[str, str]
) -> dict | None:
    """MCP initialize handshake; None means 'try the HTTP fallback'."""
    request_headers = {
        "accept": "application/json, text/event-stream",
        **{k: v for k, v in headers.items() if v},
    }
    try:
        resp = await http.post(endpoint, json=_MCP_INITIALIZE, headers=request_headers)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    payload = _parse_jsonrpc_response(resp)
    if not isinstance(payload, dict) or "result" not in payload:
        return None
    info = payload["result"].get("serverInfo") or {}
    name = info.get("name") or "mcp-server"
    version = f" v{info['version']}" if info.get("version") else ""
    return _condition(True, f"MCP initialize ok ({name}{version})")


async def probe_once(session) -> int:  # pragma: no cover - exercised via service wiring
    rows = (
        await session.execute(
            select(models.Resource)
            .where(
                models.Resource.kind == "MCPServer",
                models.Resource.deleted_at.is_(None),
            )
            .order_by(models.Resource.id)  # every server gets probed, no starvation
        )
    ).scalars().all()
    if not rows:
        return 0

    from agentrum.services.resource_service import latest_versions

    latest = await latest_versions(session, [r.id for r in rows])

    settings = get_settings()

    # Session-bound work (DB reads) happens sequentially here; the concurrent
    # phase below touches only HTTP.
    inputs: list[tuple[models.Resource, dict, dict[str, str]]] = []
    for resource in rows:
        rv = latest.get(resource.id)
        spec = (rv.spec or {}) if rv else {}
        if not spec.get("endpoint"):
            continue
        headers: dict[str, str] = {}
        if spec.get("transport") == "streamable-http" and spec.get("headers"):
            try:
                from agentrum.services import secret_service

                headers = await secret_service.resolve_env(
                    session, spec["headers"], default_namespace=resource.namespace
                )
            except Exception as exc:  # noqa: BLE001 - unresolvable headers degrade to fallback
                logger.warning(
                    "probe headers unresolved for %s/%s: %s",
                    resource.namespace, resource.name, exc.__class__.__name__,
                )
        inputs.append((resource, spec, headers))
    if not inputs:
        return 0

    semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async with httpx.AsyncClient(timeout=5, verify=settings.probe_tls_verify) as http:

        async def probe(resource: models.Resource, spec: dict, headers: dict[str, str]):  # type: ignore[no-untyped-def]
            endpoint = str(spec["endpoint"])
            async with semaphore:
                # streamable-http endpoints get the real protocol handshake.
                if spec.get("transport") == "streamable-http":
                    handshake = await _probe_streamable_http(http, endpoint, headers)
                    if handshake is not None:
                        return resource, handshake
                try:
                    resp = await http.get(endpoint)
                    return resource, _condition(resp.status_code < 500, f"HTTP {resp.status_code}")
                except Exception as exc:  # noqa: BLE001 - one bad endpoint must not sink the batch
                    logger.warning(
                        "probe failed for %s/%s: %s",
                        resource.namespace, resource.name, exc.__class__.__name__,
                    )
                    return resource, _condition(False, f"unreachable: {exc.__class__.__name__}")

        results = await asyncio.gather(*(probe(r, spec, h) for r, spec, h in inputs))

    for resource, condition in results:
        if condition is None:
            continue
        if (resource.status or {}).get("conditions") != [condition]:
            resource.status = {"conditions": [condition]}
    await session.commit()
    return len(results)


async def run_forever() -> None:  # pragma: no cover - background loop
    interval = get_settings().probe_interval_seconds
    if interval <= 0:
        logger.info("endpoint prober disabled (interval=0)")
        return
    logger.info("endpoint prober started (interval=%ss)", interval)
    while True:
        try:
            async with SessionLocal() as session:
                await probe_once(session)
        except Exception:
            logger.exception("probe tick failed")
        await asyncio.sleep(max(interval, 1))


def start_prober() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_prober(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
