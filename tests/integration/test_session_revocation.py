"""Session/credential revocation regression tests.

Disabling a user or resetting their password must take effect immediately on
every credential surface: JWT sessions (REST and MCP paths), long-lived API
tokens, and project AK/SK pairs. The behavior exists in deps/mcp_server; these
tests lock it in so it cannot silently regress.

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


class _McpCtx:
    """Minimal stand-in for an MCP Context: only headers are read."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_disable_user_kills_every_credential():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        user, team = f"rv-dis-{sfx}", f"rv-team-{sfx}"
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = await c.post("/v1/users", headers=admin, json={"username": user, "password": "password-123"})
            assert r.status_code == 201, r.text
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{team}/members", headers=admin,
                json={"username": user, "role": "admin"},
            )
            assert r.status_code == 201, r.text

            r = await c.post("/v1/auth/login", json={"username": user, "password": "password-123"})
            jwt_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # A long-lived API token and a project AK/SK from the same user.
            r = await c.post(
                "/v1/auth/tokens", headers=jwt_headers,
                json={"name": "ci", "expires_in_days": 30},
            )
            assert r.status_code == 201, r.text
            api_token = r.json()["token"]
            r = await c.post(
                f"/v1/teams/{team}/access-keys", headers=jwt_headers,
                json={"name": "reader", "scopes": ["read"]},
            )
            assert r.status_code == 201, r.text
            ak, sk = r.json()["access_key"], r.json()["secret"]

            # All three credentials work before the disable.
            assert (await c.get("/v1/auth/me", headers=jwt_headers)).status_code == 200
            assert (
                await c.get("/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"})
            ).status_code == 200
            assert (await c.get("/v1/resources", auth=(ak, sk))).status_code == 200

            # Platform admin disables the account.
            r = await c.patch(f"/v1/users/{user}", headers=admin, json={"disabled": True})
            assert r.status_code == 200, r.text

            # JWT: rejected on the REST path…
            r = await c.get("/v1/auth/me", headers=jwt_headers)
            assert r.status_code in (401, 403), r.text
            # …and on the MCP principal path.
            from agentrum.mcp_server import _resolve_principal

            with pytest.raises(PermissionError):
                await _resolve_principal(_McpCtx({"authorization": jwt_headers["Authorization"]}))
            # API token: dead.
            r = await c.get("/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"})
            assert r.status_code == 401, r.text
            # AK/SK: dead (owner disabled).
            r = await c.get("/v1/resources", auth=(ak, sk))
            assert r.status_code == 401, r.text
            # Fresh login is refused too.
            r = await c.post("/v1/auth/login", json={"username": user, "password": "password-123"})
            assert r.status_code == 403, r.text

    _run(inner())


def test_admin_password_reset_kills_sessions():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        user = f"rv-rst-{sfx}"
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.post("/v1/users", headers=admin, json={"username": user, "password": "password-123"})
            assert r.status_code == 201, r.text
            r = await c.post("/v1/auth/login", json={"username": user, "password": "password-123"})
            old_jwt = {"Authorization": f"Bearer {r.json()['access_token']}"}
            assert (await c.get("/v1/auth/me", headers=old_jwt)).status_code == 200

            # Admin-initiated reset revokes sessions issued before it.
            r = await c.patch(f"/v1/users/{user}", headers=admin, json={"new_password": "reset-pass-789"})
            assert r.status_code == 200, r.text
            r = await c.get("/v1/auth/me", headers=old_jwt)
            assert r.status_code == 401, r.text
            # The new password works.
            r = await c.post("/v1/auth/login", json={"username": user, "password": "reset-pass-789"})
            assert r.status_code == 200, r.text

    _run(inner())
