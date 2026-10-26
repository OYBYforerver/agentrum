"""Integration tests for the code-review fixes: ownership removal guard and
reconciler keyset pagination."""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ARK_INTEGRATION") != "1",
        reason="integration tests require ARK_INTEGRATION=1 and a test database",
    ),
]


def _suffix():
    return uuid.uuid4().hex[:8]


def test_owner_cannot_be_removed_until_ownership_transfers():
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        team, member = f"own-{sfx}", f"mate-{sfx}"
        app = __import__("agentrum.main", fromlist=["app"]).app
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text
            r = await c.post(
                "/v1/users",
                headers=admin,
                json={"username": member, "password": "password-123"},
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{team}/members",
                headers=admin,
                json={"username": member, "role": "admin"},
            )
            assert r.status_code == 201, r.text

            # The owner cannot be removed: owner_user_id is the transfer
            # anchor and must never dangle on a non-member.
            r = await c.delete(f"/v1/teams/{team}/members/admin", headers=admin)
            assert r.status_code == 409, r.text

            # After transferring ownership away, the old owner is removable.
            r = await c.patch(f"/v1/teams/{team}/owner", headers=admin, json={"username": member})
            assert r.status_code == 200, r.text
            r = await c.delete(f"/v1/teams/{team}/members/admin", headers=admin)
            assert r.status_code == 204, r.text

    asyncio.run(inner())


def test_reconciler_processes_every_deployment_past_one_page(monkeypatch):
    from agentrum.db import models
    from agentrum.db.engine import SessionLocal
    from agentrum.main import _ensure_bootstrap_admin
    from agentrum.services.deployments import reconciler

    monkeypatch.setattr(reconciler, "_RECONCILE_BATCH", 2)

    class _StubAdapter:
        def __init__(self):
            self.applied = 0

        async def apply(self, plan):
            self.applied += 1
            return {"type": "Ready", "status": "True", "message": "ok"}

        async def remove(self, plan):
            return {"type": "Ready", "status": "True", "message": "removed"}

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        ns = f"pgn-{sfx}"
        total = 7  # four pages at batch=2
        async with SessionLocal() as session:
            admin = (
                await session.execute(select(models.User).where(models.User.username == "admin"))
            ).scalar_one()
            team = models.Team(name=ns, owner_user_id=admin.id)
            session.add(team)
            await session.flush()
            session.add(models.Namespace(name=ns, team_id=team.id))
            await session.flush()
            for i in range(total):
                res = models.Resource(
                    kind="Deployment",
                    namespace=ns,
                    name=f"d{i}",
                    visibility="internal",
                    created_by=admin.id,
                )
                session.add(res)
                await session.flush()
                session.add(
                    models.ResourceVersion(
                        resource_id=res.id,
                        version=1,
                        tag=None,
                        # target does not exist → every row gets a condition
                        spec={
                            "target_kind": "Agent",
                            "target_namespace": "nope",
                            "target_name": "missing",
                        },
                        published_by=admin.id,
                    )
                )
            await session.commit()

        adapter = _StubAdapter()
        try:
            async with SessionLocal() as session:
                await reconciler.reconcile_tick(session, adapter)
                rows = (
                    (
                        await session.execute(
                            select(models.Resource).where(models.Resource.namespace == ns)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == total
                # every row was visited — nothing starved past the first page
                statuses = [dict(r.status or {}) for r in rows]
                assert all(s.get("conditions") for s in statuses), statuses
        finally:
            async with SessionLocal() as session:
                await session.execute(
                    sa_delete(models.Resource).where(models.Resource.namespace == ns)
                )
                await session.execute(
                    sa_delete(models.Namespace).where(models.Namespace.name == ns)
                )
                await session.execute(sa_delete(models.Team).where(models.Team.name == ns))
                await session.commit()

    asyncio.run(inner())
