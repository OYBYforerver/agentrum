"""Regression tests for the security fixes.

Gate: ARK_INTEGRATION=1 plus ARK_DATABASE_URL pointing at a dedicated test
database (same as test_flow.py).
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


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _run(coro):
    return asyncio.run(coro)


def _app():
    import agentrum.main

    return agentrum.main.app


def _admin_client_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _setup(c, admin: dict, sfx: str):
    """Create a publisher team (with an admin member) + a subscriber team.
    Returns (pub_team, sub_team, pub_headers)."""
    pub, sub = f"rg-pub-{sfx}", f"rg-sub-{sfx}"
    r = await c.post("/v1/teams", headers=admin, json={"name": pub})
    assert r.status_code == 201, r.text
    r = await c.post("/v1/teams", headers=admin, json={"name": sub})
    assert r.status_code == 201, r.text
    r = await c.post(
        "/v1/users", headers=admin, json={"username": f"rg-pub-{sfx}", "password": "password-123"}
    )
    assert r.status_code == 201, r.text
    r = await c.post(
        f"/v1/teams/{pub}/members", headers=admin,
        json={"username": f"rg-pub-{sfx}", "role": "admin"},
    )
    assert r.status_code == 201, r.text
    r = await c.post(
        "/v1/auth/login",
        json={"username": f"rg-pub-{sfx}", "password": "password-123"},
    )
    assert r.status_code == 200, r.text
    return pub, sub, {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_wildcard_subscription_grants_internal_only():  # pragma: no cover
    """A wildcard subscription must expose INTERNAL resources but never
    restricted ones (which require an approved exact-name subscription)."""
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = _admin_client_headers(r.json()["access_token"])
            pub, sub, pub_h = await _setup(c, admin, sfx)

            r = await c.put(
                f"/v1/resources/Agent/{pub}/open-agent", headers=pub_h,
                json={"spec": {"image": "reg/open:1"}, "visibility": "internal", "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            r = await c.put(
                f"/v1/resources/Agent/{pub}/secret-agent", headers=pub_h,
                json={"spec": {"image": "reg/secret:1"}, "visibility": "restricted", "tag": "v1"},
            )
            assert r.status_code == 201, r.text

            # subscriber team member requests a wildcard subscription
            r = await c.post(
                "/v1/users", headers=admin, json={"username": f"rg-subm-{sfx}", "password": "password-123"}
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{sub}/members", headers=admin,
                json={"username": f"rg-subm-{sfx}", "role": "member"},
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                "/v1/auth/login", headers=admin,
                json={"username": f"rg-subm-{sfx}", "password": "password-123"},
            )
            sub_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.post(
                f"/v1/teams/{sub}/subscriptions", headers=sub_h,
                json={"kind": "Agent", "namespace": pub, "name": "*"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["status"] == "active", r.text

            # internal resource: visible and readable
            r = await c.get(f"/v1/resources/Agent/{pub}/open-agent", headers=sub_h)
            assert r.status_code == 200, r.text
            # restricted resource: wildcard must NOT grant it
            r = await c.get(f"/v1/resources/Agent/{pub}/secret-agent", headers=sub_h)
            assert r.status_code == 403, r.text
            r = await c.get(
                "/v1/resources", headers=sub_h, params={"kind": "Agent", "namespace": pub}
            )
            names = [it["name"] for it in r.json()["items"]]
            assert "open-agent" in names
            assert "secret-agent" not in names

    _run(inner())


def test_revoked_subscription_can_be_recreated():  # pragma: no cover
    """Reject/revoke must not permanently lock the target: the subscription
    row is revived on a new request."""
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = _admin_client_headers(r.json()["access_token"])
            pub, sub, pub_h = await _setup(c, admin, sfx)

            r = await c.put(
                f"/v1/resources/Agent/{pub}/restricted-agent", headers=pub_h,
                json={"spec": {"image": "reg/x:1"}, "visibility": "restricted", "tag": "v1"},
            )
            assert r.status_code == 201, r.text

            r = await c.post(
                "/v1/users", headers=admin, json={"username": f"rg-suba-{sfx}", "password": "password-123"}
            )
            r = await c.post(
                f"/v1/teams/{sub}/members", headers=admin,
                json={"username": f"rg-suba-{sfx}", "role": "admin"},
            )
            r = await c.post(
                "/v1/auth/login", headers=admin,
                json={"username": f"rg-suba-{sfx}", "password": "password-123"},
            )
            sub_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # request → reject → request again must not 409
            r = await c.post(
                f"/v1/teams/{sub}/subscriptions", headers=sub_h,
                json={"kind": "Agent", "namespace": pub, "name": "restricted-agent"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["status"] == "pending_approval", r.text
            sub_id = r.json()["id"]
            r = await c.post(f"/v1/subscriptions/{sub_id}/reject", headers=pub_h)
            assert r.status_code == 200, r.text

            r = await c.post(
                f"/v1/teams/{sub}/subscriptions", headers=sub_h,
                json={"kind": "Agent", "namespace": pub, "name": "restricted-agent"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["status"] == "pending_approval", r.text
            # and the owner can now approve it
            sub_id = r.json()["id"]
            r = await c.post(f"/v1/subscriptions/{sub_id}/approve", headers=pub_h)
            assert r.status_code == 200, r.text
            r = await c.get(
                f"/v1/resources/Agent/{pub}/restricted-agent", headers=sub_h
            )
            assert r.status_code == 200, r.text

    _run(inner())


def test_patch_visibility_invariants():  # pragma: no cover
    """PATCH cannot make a Secret internal, and a developer cannot patch a
    Deployment."""
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = _admin_client_headers(r.json()["access_token"])
            pub, _sub, pub_h = await _setup(c, admin, sfx)

            r = await c.put(
                f"/v1/resources/Secret/{pub}/api-keys", headers=pub_h,
                json={"spec": {"data": {"key": "value"}}},
            )
            assert r.status_code == 201, r.text
            assert r.json()["visibility"] == "restricted", r.text

            r = await c.patch(
                f"/v1/resources/Secret/{pub}/api-keys", headers=pub_h,
                json={"visibility": "internal"},
            )
            assert r.status_code == 400, r.text

            # developer role: can publish ordinary resources, cannot patch a Deployment
            r = await c.post(
                "/v1/users", headers=admin, json={"username": f"rg-dev-{sfx}", "password": "password-123"}
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{pub}/members", headers=admin,
                json={"username": f"rg-dev-{sfx}", "role": "developer"},
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                "/v1/auth/login", headers=admin,
                json={"username": f"rg-dev-{sfx}", "password": "password-123"},
            )
            dev_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = await c.put(
                f"/v1/resources/Agent/{pub}/dev-agent", headers=dev_h,
                json={"spec": {"image": "reg/dev:1"}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            r = await c.put(
                f"/v1/resources/Deployment/{pub}/dev-deploy", headers=dev_h,
                json={"spec": {"target_kind": "Agent", "target_namespace": pub,
                               "target_name": "dev-agent"}},
            )
            assert r.status_code == 403, r.text  # developer cannot create Deployments
            # admin publishes the Deployment; the developer still cannot PATCH it
            r = await c.put(
                f"/v1/resources/Deployment/{pub}/dev-deploy", headers=pub_h,
                json={"spec": {"target_kind": "Agent", "target_namespace": pub,
                               "target_name": "dev-agent"}},
            )
            assert r.status_code == 201, r.text
            r = await c.patch(
                f"/v1/resources/Deployment/{pub}/dev-deploy", headers=dev_h,
                json={"description": "sneak"},
            )
            assert r.status_code == 403, r.text

    _run(inner())


def test_cross_namespace_secret_ref_rejected():  # pragma: no cover
    """secretRef may only point inside the referencing resource's namespace —
    the reconciler runs without an actor, so anything else would leak."""
    from agentrum import errors
    from agentrum.db.engine import SessionLocal
    from agentrum.services import secret_service

    async def inner():
        async with SessionLocal() as session:
            with pytest.raises(errors.PermissionDeniedError):
                await secret_service.resolve_env(
                    session,
                    [{"name": "TOKEN", "value_from": {"secret_ref": {
                        "name": "creds", "key": "token", "namespace": "other-team"}}}],
                    default_namespace="my-team",
                )

    _run(inner())


def test_body_size_limit_caps_chunked_requests():  # pragma: no cover
    """A chunked upload with no Content-Length is still capped."""
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        big = b"x" * (3 * 1024 * 1024)  # 3 MiB, default cap is 2 MiB

        async def stream():
            yield big  # async-iterable body → no Content-Length → chunked

        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            headers = _admin_client_headers(r.json()["access_token"])
            r = await c.post(
                "/v1/teams", headers=headers, content=stream(),
            )
            assert r.status_code == 413, r.status_code

    _run(inner())


def test_password_change_invalidates_old_sessions():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = _admin_client_headers(r.json()["access_token"])
            await _setup(c, admin, sfx)
            r = await c.post(
                "/v1/users", headers=admin, json={"username": f"rg-pwd-{sfx}", "password": "password-123"}
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                "/v1/auth/login",
                json={"username": f"rg-pwd-{sfx}", "password": "password-123"},
            )
            old_token = r.json()["access_token"]
            r = await c.post(
                "/v1/auth/change-password",
                headers={"Authorization": f"Bearer {old_token}"},
                json={"old_password": "password-123", "new_password": "new-password-456"},
            )
            assert r.status_code == 204, r.text
            # the pre-change token no longer authenticates
            r = await c.get(
                "/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}
            )
            assert r.status_code == 401, r.text

    _run(inner())


def test_demoting_ak_creator_disables_the_key():  # pragma: no cover
    """An AK stops working once its creator loses the role the key requires."""
    import base64

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = _admin_client_headers(r.json()["access_token"])
            pub, _sub, pub_h = await _setup(c, admin, sfx)

            # creator is an admin; key carries publish scope
            r = await c.post(
                f"/v1/teams/{pub}/access-keys", headers=pub_h,
                json={"name": "ci", "scopes": ["read", "publish"]},
            )
            assert r.status_code == 201, r.text
            basic = {
                "Authorization": "Basic "
                + base64.b64encode(
                    f"{r.json()['access_key']}:{r.json()['secret']}".encode()
                ).decode()
            }
            r = await c.get("/v1/resources", headers=basic)
            assert r.status_code == 200, r.text

            # demote the creator below developer → key loses its powers
            r = await c.patch(
                f"/v1/teams/{pub}/members/rg-pub-{sfx}", headers=pub_h,
                json={"role": "member"},
            )
            assert r.status_code == 200, r.text
            r = await c.get("/v1/resources", headers=basic)
            assert r.status_code == 401, r.text

    _run(inner())


def test_include_deleted_is_admin_only():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = _admin_client_headers(r.json()["access_token"])
            pub, _sub, pub_h = await _setup(c, admin, sfx)
            r = await c.put(
                f"/v1/resources/Agent/{pub}/gone-agent", headers=pub_h,
                json={"spec": {"image": "reg/g:1"}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            r = await c.delete(f"/v1/resources/Agent/{pub}/gone-agent", headers=pub_h)
            assert r.status_code == 204, r.text

            r = await c.get(
                "/v1/resources", headers=pub_h, params={"include_deleted": "true"}
            )
            assert r.status_code == 403, r.text
            r = await c.get(
                "/v1/resources", headers=admin, params={"include_deleted": "true"}
            )
            assert r.status_code == 200, r.text

    _run(inner())
