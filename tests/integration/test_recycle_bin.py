"""Recycle bin: soft-deleted resources restore on re-apply, and the
retention prune removes expired ones for good (with cascading versions)."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ARK_INTEGRATION") != "1",
        reason="integration tests require ARK_INTEGRATION=1 and a test database",
    ),
]


def _suffix():
    return uuid.uuid4().hex[:8]


def test_recycle_bin_restore_and_expiry():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.db.engine import SessionLocal
    from agentrum.main import _ensure_bootstrap_admin
    from agentrum.services.maintenance_service import prune_once

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        team, name = f"rb-{sfx}", "pay-gw"
        app = __import__("agentrum.main", fromlist=["app"]).app
        spec = {"transport": "streamable-http", "endpoint": "https://x.internal/mcp"}
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text

            r = await c.put(
                f"/v1/resources/MCPServer/{team}/{name}", headers=admin,
                json={"spec": spec, "tag": "v1"},
            )
            assert r.status_code == 201, r.text

            # Soft delete → visible only via the admin tombstone view.
            r = await c.delete(f"/v1/resources/MCPServer/{team}/{name}", headers=admin)
            assert r.status_code == 204, r.text
            r = await c.get(f"/v1/resources/MCPServer/{team}/{name}", headers=admin)
            assert r.status_code == 404, r.text
            r = await c.get(
                "/v1/resources", headers=admin,
                params={"kind": "MCPServer", "namespace": team, "include_deleted": True},
            )
            assert r.status_code == 200, r.text
            assert name in [i["name"] for i in r.json()["items"]], r.text

            # Re-apply restores (with a new immutable tag).
            r = await c.put(
                f"/v1/resources/MCPServer/{team}/{name}", headers=admin,
                json={"spec": spec, "tag": "v2"},
            )
            assert r.status_code in (200, 201), r.text
            r = await c.get(f"/v1/resources/MCPServer/{team}/{name}", headers=admin)
            assert r.status_code == 200 and r.json()["deleted_at"] is None, r.text
            assert r.json()["latest_version"]["tag"] == "v2"

            # Age the tombstone past the retention window and prune.
            r = await c.delete(f"/v1/resources/MCPServer/{team}/{name}", headers=admin)
            assert r.status_code == 204, r.text
            from sqlalchemy import text

            async with SessionLocal() as session:
                await session.execute(
                    text(
                        "UPDATE resources SET deleted_at = :old "
                        "WHERE namespace = :ns AND name = :nm"
                    ),
                    {"old": datetime.now(UTC) - timedelta(days=45), "ns": team, "nm": name},
                )
                await session.commit()
                summary = await prune_once()
            assert summary.get("resources_purged", 0) >= 1, summary
            r = await c.get(
                "/v1/resources", headers=admin,
                params={"kind": "MCPServer", "namespace": team, "include_deleted": True},
            )
            assert r.status_code == 200, r.text
            assert name not in [i["name"] for i in r.json()["items"]]  # gone for good

    asyncio.run(inner())
