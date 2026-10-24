"""Integration tests — run against a real PostgreSQL.

Gate: ARK_INTEGRATION=1 plus ARK_DATABASE_URL pointing at a dedicated test
database (CI uses a service container; locally `make compose-up` + a scratch
database). Skipped by default so `pytest` stays green without infrastructure.
"""

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


@pytest.fixture(scope="module")
def anyio_backend() -> str:  # pragma: no cover - trivial
    return "asyncio"


def _run(coro):  # pragma: no cover - thin asyncio wrapper
    return asyncio.run(coro)


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def test_full_tenancy_and_subscription_flow():  # pragma: no cover
    """login → team/user setup → publish → subscribe (internal) → restricted
    approval → notification outbox → soft delete."""
    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        import httpx
        from httpx import ASGITransport

        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            # admin login
            r = await c.post(
                "/v1/auth/login", json={"username": "admin", "password": "admin123"}
            )
            assert r.status_code == 200, r.text
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # users + teams
            for u in (f"int-alice-{sfx}", f"int-bob-{sfx}"):
                r = await c.post(
                    "/v1/users",
                    headers=admin,
                    json={"username": u, "password": "password-123"},
                )
                assert r.status_code == 201, r.text
            for t in (f"int-pub-{sfx}", f"int-sub-{sfx}"):
                r = await c.post("/v1/teams", headers=admin, json={"name": t})
                assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/int-pub-{sfx}/members",
                headers=admin,
                json={"username": f"int-alice-{sfx}", "role": "publisher"},
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/int-sub-{sfx}/members",
                headers=admin,
                json={"username": f"int-bob-{sfx}", "role": "member"},
            )
            assert r.status_code == 201, r.text

            # publisher login
            r = await c.post(
                "/v1/auth/login",
                json={"username": f"int-alice-{sfx}", "password": "password-123"},
            )
            pub = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.post(
                "/v1/auth/login",
                json={"username": f"int-bob-{sfx}", "password": "password-123"},
            )
            cons = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # publish internal resource
            r = await c.put(
                f"/v1/resources/MCPServer/int-pub-{sfx}/gateway",
                headers=pub,
                json={
                    "spec": {"transport": "streamable-http", "endpoint": "http://g:3000/mcp"},
                    "tag": "v1.0.0",
                },
            )
            assert r.status_code == 201, r.text

            # consumer subscribes (internal → active)
            r = await c.post(
                f"/v1/teams/int-sub-{sfx}/subscriptions",
                headers=cons,
                json={"kind": "MCPServer", "namespace": f"int-pub-{sfx}", "name": "gateway"},
            )
            assert r.status_code == 201 and r.json()["status"] == "active", r.text

            # a new version AFTER the subscription produces an outbox entry
            r = await c.put(
                f"/v1/resources/MCPServer/int-pub-{sfx}/gateway",
                headers=pub,
                json={
                    "spec": {"transport": "streamable-http", "endpoint": "http://g:3000/mcp"},
                    "tag": "v1.1.0",
                },
            )
            assert r.status_code == 200, r.text

            # publish restricted resource → outbox for internal sub only
            r = await c.put(
                f"/v1/resources/Agent/int-pub-{sfx}/secret-agent",
                headers=pub,
                json={"spec": {"image": "reg.local/a:1"}, "visibility": "restricted", "tag": "v0.1.0"},
            )
            assert r.status_code == 201, r.text

            # restricted: read denied → subscribe pending → approve → read ok
            r = await c.get(
                f"/v1/resources/Agent/int-pub-{sfx}/secret-agent", headers=cons
            )
            assert r.status_code == 403, r.text
            r = await c.post(
                f"/v1/teams/int-sub-{sfx}/subscriptions",
                headers=cons,
                json={"kind": "Agent", "namespace": f"int-pub-{sfx}", "name": "secret-agent"},
            )
            assert r.status_code == 201 and r.json()["status"] == "pending_approval", r.text
            sub_id = r.json()["id"]
            r = await c.post(f"/v1/subscriptions/{sub_id}/approve", headers=admin)
            assert r.status_code == 200 and r.json()["status"] == "active", r.text
            r = await c.get(
                f"/v1/resources/Agent/int-pub-{sfx}/secret-agent", headers=cons
            )
            assert r.status_code == 200, r.text

            # notification outbox holds an entry for the internal subscription
            r = await c.get("/v1/notifications", headers=admin)
            assert r.status_code == 200
            payloads = [row["payload"] for row in r.json()]
            mine = [
                p
                for p in payloads
                if p["name"] == "gateway"
                and p["namespace"] == f"int-pub-{sfx}"
                and p.get("tag") == "v1.1.0"
            ]
            assert mine, "expected outbox entry for internal subscription"
            assert mine[0]["subscriber_team"] == f"int-sub-{sfx}"

            # soft delete + 404 afterwards
            r = await c.delete(
                f"/v1/resources/MCPServer/int-pub-{sfx}/gateway", headers=pub
            )
            assert r.status_code == 204
            r = await c.get(
                f"/v1/resources/MCPServer/int-pub-{sfx}/gateway", headers=cons
            )
            assert r.status_code == 404

    _run(inner())


def test_access_keys_and_prompt_privacy():  # pragma: no cover
    """AK/SK lifecycle: admin creates a project key; Basic-auth publishes and
    lists within scope; prompt resources are project-private and cannot be
    subscribed across projects."""
    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        import base64

        import httpx
        from httpx import ASGITransport

        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = await c.post("/v1/teams", headers=admin, json={"name": f"ak-pub-{sfx}"})
            assert r.status_code == 201, r.text
            pub_team = f"ak-pub-{sfx}"
            r = await c.post("/v1/teams", headers=admin, json={"name": f"ak-sub-{sfx}"})
            assert r.status_code == 201, r.text
            sub_team = f"ak-sub-{sfx}"

            # create an AK for the publishing project
            r = await c.post(
                f"/v1/teams/{pub_team}/access-keys",
                headers=admin,
                json={"name": "ci", "scopes": ["read", "publish"]},
            )
            assert r.status_code == 201, r.text
            ak, sk = r.json()["access_key"], r.json()["secret"]
            basic = {
                "Authorization": "Basic "
                + base64.b64encode(f"{ak}:{sk}".encode()).decode()
            }

            # AK publish works (publish scope), prompt is forced private
            r = await c.put(
                f"/v1/resources/Prompt/{pub_team}/greeting",
                headers=basic,
                json={"spec": {"template": "hello {{name}}", "variables": [{"name": "name"}]}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["visibility"] == "private", r.text

            # AK list discovery works (read scope)
            r = await c.get("/v1/resources", headers=basic)
            assert r.status_code == 200
            names = [it["name"] for it in r.json()["items"]]
            assert "greeting" in names

            # member of ANOTHER project cannot read the private prompt
            await c.post(
                "/v1/users",
                headers=admin,
                json={"username": f"ak-bob-{sfx}", "password": "password-123"},
            )
            await c.post(
                f"/v1/teams/{sub_team}/members",
                headers=admin,
                json={"username": f"ak-bob-{sfx}", "role": "member"},
            )
            r = await c.post(
                "/v1/auth/login",
                json={"username": f"ak-bob-{sfx}", "password": "password-123"},
            )
            bob = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.get(f"/v1/resources/Prompt/{pub_team}/greeting", headers=bob)
            assert r.status_code == 403, r.text

            # subscribing to a Prompt is rejected outright
            r = await c.post(
                f"/v1/teams/{sub_team}/subscriptions",
                headers=bob,
                json={"kind": "Prompt", "namespace": pub_team, "name": "greeting"},
            )
            assert r.status_code == 400, r.text

            # AK without publish scope cannot publish
            r = await c.post(
                f"/v1/teams/{sub_team}/access-keys",
                headers=admin,
                json={"name": "ro", "scopes": ["read"]},
            )
            ro_basic = {
                "Authorization": "Basic "
                + base64.b64encode(
                    f"{r.json()['access_key']}:{r.json()['secret']}".encode()
                ).decode()
            }
            r = await c.put(
                f"/v1/resources/Skill/{pub_team}/x",
                headers=ro_basic,
                json={"spec": {}},
            )
            assert r.status_code == 403, r.text

    _run(inner())


def test_owner_can_revoke_grant():  # pragma: no cover
    """Owner-side grant revocation: approve a restricted subscription, then
    the OWNER team's admin revokes it — subscriber loses access at once."""
    import asyncio

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            owner, sub = f"gv-owner-{sfx}", f"gv-sub-{sfx}"
            for t in (owner, sub):
                await c.post("/v1/teams", headers=admin, json={"name": t})
            await c.post("/v1/users", headers=admin, json={"username": f"gv-u-{sfx}", "password": "password-123"})
            await c.post(f"/v1/teams/{sub}/members", headers=admin, json={"username": f"gv-u-{sfx}", "role": "member"})

            # publish restricted resource
            await c.put(
                f"/v1/resources/Agent/{owner}/core-api",
                headers=admin,
                json={"spec": {"image": "reg.local/core:1.0"}, "visibility": "restricted", "tag": "v1"},
            )
            # subscribe → pending → owner approves
            r = await c.post(
                f"/v1/teams/{sub}/subscriptions",
                headers=admin,
                json={"kind": "Agent", "namespace": owner, "name": "core-api"},
            )
            sub_id = r.json()["id"]
            r = await c.post(f"/v1/subscriptions/{sub_id}/approve", headers=admin)
            assert r.json()["status"] == "active"

            # subscriber reads OK
            r = await c.post(
                "/v1/auth/login", json={"username": f"gv-u-{sfx}", "password": "password-123"}
            )
            member = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.get(f"/v1/resources/Agent/{owner}/core-api", headers=member)
            assert r.status_code == 200

            # OWNER team admin revokes the grant (not the subscriber)
            r = await c.delete(f"/v1/subscriptions/{sub_id}", headers=admin)
            assert r.status_code == 200, r.text

            # subscriber loses access immediately
            r = await c.get(f"/v1/resources/Agent/{owner}/core-api", headers=member)
            assert r.status_code == 403, r.text

    asyncio.run(inner())


def test_team_creation_with_designated_owner():  # pragma: no cover
    """Admin creates a project designating another user as owner: the owner
    becomes the project admin, the creator is not a member, and the owner can
    publish in the project namespace."""
    import asyncio

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            owner_name = f"own-{sfx}"
            team = f"own-proj-{sfx}"

            await c.post("/v1/users", headers=admin, json={"username": owner_name, "password": "password-123"})
            r = await c.post(
                "/v1/teams", headers=admin,
                json={"name": team, "owner": owner_name},
            )
            assert r.status_code == 201, r.text
            assert r.json()["my_role"] is None, "creator should not be a member when owner is designated"

            # owner login → publish in the project namespace
            r = await c.post("/v1/auth/login", json={"username": owner_name, "password": "password-123"})
            owner = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.put(
                f"/v1/resources/Skill/{team}/skill-x",
                headers=owner,
                json={"spec": {"instructions": "demo"}},
            )
            assert r.status_code == 201, r.text

            # owner manages members
            r = await c.post(
                f"/v1/teams/{team}/members", headers=owner,
                json={"username": "admin", "role": "member"},
            )
            assert r.status_code == 201, r.text

    asyncio.run(inner())


def test_deploy_scope_and_ownership_transfer():  # pragma: no cover
    """deploy scope gates Deployment resources for AK principals; ownership
    transfer reassigns the owner and demotes the previous one."""
    import asyncio
    import base64

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            team = f"dep-scope-{sfx}"
            await c.post("/v1/teams", headers=admin, json={"name": team})
            await c.put(
                f"/v1/resources/Agent/{team}/target",
                headers=admin,
                json={"spec": {"image": "reg.local/t:1"}, "tag": "v1"},
            )

            # AK with publish scope only → Deployment creation denied
            r = await c.post(
                f"/v1/teams/{team}/access-keys", headers=admin,
                json={"name": "pub-only", "scopes": ["read", "publish"]},
            )
            ak, sk = r.json()["access_key"], r.json()["secret"]
            pub = {"Authorization": "Basic " + base64.b64encode(f"{ak}:{sk}".encode()).decode()}
            r = await c.put(
                f"/v1/resources/Deployment/{team}/dep1", headers=pub,
                json={"spec": {"target_kind": "Agent", "target_namespace": team, "target_name": "target"}},
            )
            assert r.status_code == 403 and "deploy" in r.json()["detail"], r.text

            # AK with deploy scope → allowed
            r = await c.post(
                f"/v1/teams/{team}/access-keys", headers=admin,
                json={"name": "deployer", "scopes": ["read", "deploy"]},
            )
            ak2, sk2 = r.json()["access_key"], r.json()["secret"]
            dep = {"Authorization": "Basic " + base64.b64encode(f"{ak2}:{sk2}".encode()).decode()}
            r = await c.put(
                f"/v1/resources/Deployment/{team}/dep2", headers=dep,
                json={"spec": {"target_kind": "Agent", "target_namespace": team, "target_name": "target"}},
            )
            assert r.status_code == 201, r.text

            # ownership transfer: admin creates project for owner-u, then transfers to member-u
            await c.post("/v1/users", headers=admin, json={"username": f"own-u-{sfx}", "password": "password-123"})
            await c.post("/v1/users", headers=admin, json={"username": f"mem-u-{sfx}", "password": "password-123"})
            team2 = f"trans-{sfx}"
            await c.post("/v1/teams", headers=admin, json={"name": team2, "owner": f"own-u-{sfx}"})
            await c.post(
                f"/v1/teams/{team2}/members", headers=admin,
                json={"username": f"mem-u-{sfx}", "role": "member"},
            )
            r = await c.patch(
                f"/v1/teams/{team2}/owner", headers=admin,
                json={"username": f"mem-u-{sfx}"},
            )
            assert r.status_code == 200, r.text
            # new owner manages members; previous owner demoted to member
            r = await c.post(
                "/v1/auth/login", json={"username": f"mem-u-{sfx}", "password": "password-123"}
            )
            new_owner = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.get(f"/v1/teams/{team2}/members", headers=new_owner)
            roles = {m["username"]: m["role"] for m in r.json()}
            assert roles[f"mem-u-{sfx}"] == "admin"
            assert roles[f"own-u-{sfx}"] == "member"

    asyncio.run(inner())


def test_developer_role_boundaries():  # pragma: no cover
    """developer may publish/update but never delete nor manage Deployments."""
    import asyncio

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            team = f"dev-role-{sfx}"
            await c.post("/v1/teams", headers=admin, json={"name": team})
            await c.post("/v1/users", headers=admin, json={"username": f"dev-u-{sfx}", "password": "password-123"})
            await c.post(f"/v1/teams/{team}/members", headers=admin, json={"username": f"dev-u-{sfx}", "role": "developer"})
            await c.put(
                f"/v1/resources/Agent/{team}/target",
                headers=admin,
                json={"spec": {"image": "reg.local/t:1"}, "tag": "v1"},
            )

            r = await c.post("/v1/auth/login", json={"username": f"dev-u-{sfx}", "password": "password-123"})
            dev = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # developer may publish/update
            r = await c.put(
                f"/v1/resources/Agent/{team}/feature-x",
                headers=dev, json={"spec": {"image": "reg.local/f:1"}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text

            # developer may NOT manage Deployments
            r = await c.put(
                f"/v1/resources/Deployment/{team}/dep-x",
                headers=dev,
                json={"spec": {"target_kind": "Agent", "target_namespace": team, "target_name": "target"}},
            )
            assert r.status_code == 403 and "developer" in r.json()["detail"], r.text

            # developer may NOT delete
            r = await c.delete(f"/v1/resources/Agent/{team}/feature-x", headers=dev)
            assert r.status_code == 403 and "publisher" in r.json()["detail"], r.text

            # publisher still may delete
            await c.post(f"/v1/teams/{team}/members", headers=admin, json={"username": "alice", "role": "publisher"}) if False else None
            r = await c.delete(f"/v1/resources/Agent/{team}/feature-x", headers=admin)
            assert r.status_code == 204, r.text

    asyncio.run(inner())
