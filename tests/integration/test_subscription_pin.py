"""Subscription version pin: pinned subscribers get an explicit "new version
available, you are pinned" notice instead of an upgrade implication; the pin
is patchable per subscription."""

import asyncio
import os
import uuid

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ARK_INTEGRATION") != "1",
        reason="integration tests require ARK_INTEGRATION=1 and a test database",
    ),
]


def _suffix():
    return uuid.uuid4().hex[:8]


def test_subscription_pin_and_drift_notice():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.db import models
    from agentrum.db.engine import SessionLocal
    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        pub, sub = f"pin-pub-{sfx}", f"pin-sub-{sfx}"
        app = __import__("agentrum.main", fromlist=["app"]).app
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            for t in (pub, sub):
                r = await c.post("/v1/teams", headers=admin, json={"name": t})
                assert r.status_code == 201, r.text

            r = await c.put(
                f"/v1/resources/MCPServer/{pub}/pay-gw",
                headers=admin,
                json={
                    "spec": {"transport": "streamable-http", "endpoint": "https://x.internal/mcp"},
                    "tag": "v1.0.0",
                    "visibility": "internal",
                },
            )
            assert r.status_code == 201, r.text

            # Subscribe pinned to v1.0.0.
            r = await c.post(
                f"/v1/teams/{sub}/subscriptions", headers=admin,
                json={
                    "kind": "MCPServer", "namespace": pub, "name": "pay-gw",
                    "pinned_tag": "v1.0.0",
                },
            )
            assert r.status_code == 201, r.text
            sub_id = r.json()["id"]
            assert r.json()["pinned_tag"] == "v1.0.0"

            # A new tag publishes → the notice carries the pin hint.
            r = await c.put(
                f"/v1/resources/MCPServer/{pub}/pay-gw",
                headers=admin,
                json={
                    "spec": {"transport": "streamable-http", "endpoint": "https://x.internal/mcp"},
                    "tag": "v1.1.0",
                },
            )
            assert r.status_code in (200, 201), r.text  # 200 = new version of existing

            from sqlalchemy import select

            async with SessionLocal() as session:
                rows = (
                    await session.execute(
                        select(models.NotificationOutbox).where(
                            models.NotificationOutbox.event_type == "resource.published"
                        )
                    )
                ).scalars().all()
            mine = [
                n for n in rows
                if n.payload.get("namespace") == pub and n.payload.get("name") == "pay-gw"
            ]
            assert mine, "no published notification queued"
            latest = mine[-1].payload
            assert latest["pinned_tag"] == "v1.0.0"
            assert "pinned to v1.0.0" in latest["note"]
            assert latest["tag"] == "v1.1.0"

            # PATCH re-pins; null clears.
            r = await c.patch(
                f"/v1/subscriptions/{sub_id}", headers=admin, json={"pinned_tag": "v1.1.0"}
            )
            assert r.status_code == 200 and r.json()["pinned_tag"] == "v1.1.0", r.text
            r = await c.patch(
                f"/v1/subscriptions/{sub_id}", headers=admin, json={"pinned_tag": None}
            )
            assert r.status_code == 200 and r.json()["pinned_tag"] is None, r.text
            r = await c.patch(
                f"/v1/subscriptions/{sub_id}", headers=admin, json={"pinned_tag": ""}
            )
            assert r.status_code == 400, r.text

    asyncio.run(inner())
