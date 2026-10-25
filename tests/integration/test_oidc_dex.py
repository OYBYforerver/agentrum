"""OIDC code-flow handshake against a real Dex IdP.

Runs only when ARK_INTEGRATION=1 *and* a Dex instance answers on
ARK_OIDC_GENERIC_ISSUER (CI starts one from tests/integration/dex.yaml;
locally: docker run -p 5556:5556 -v $PWD/tests/integration/dex.yaml:/config.yaml
ghcr.io/dexidp/dex:v2.41.1 serve /config.yaml).

The whole browser-side flow is driven through one httpx client: requests to
the registry host are mounted onto the in-process ASGI app, requests to Dex
go over real HTTP — cookies (OIDC state, Dex session) round-trip exactly as
they would in a browser.
"""

import asyncio
import os
import re
import uuid

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ARK_INTEGRATION") != "1",
        reason="integration tests require ARK_INTEGRATION=1 and a test database",
    ),
    pytest.mark.skipif(
        not os.environ.get("ARK_OIDC_GENERIC_ISSUER", "").startswith("http"),
        reason="OIDC flow test needs a configured issuer (CI runs Dex)",
    ),
]


def _suffix():
    return uuid.uuid4().hex[:8]


async def _drive_flow(c, base: str) -> dict:
    """Full browser flow: registry login redirect → Dex form login →
    callback → JSON token response."""
    r = await c.get(f"{base}/v1/auth/oidc/generic/login", follow_redirects=False)
    assert r.status_code == 307, r.text
    assert r.headers["location"].startswith(os.environ["ARK_OIDC_GENERIC_ISSUER"])

    # Dex authorize → (302) → login page
    r = await c.get(r.headers["location"], follow_redirects=True)
    assert r.status_code == 200, r.text
    import html as html_mod

    action = str(
        r.url.join(html_mod.unescape(re.search(r'<form[^>]+action="([^"]+)"', r.text).group(1)))
    )

    r = await c.post(
        action,
        data={"login": "dev@example.com", "password": "password"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    nxt = r.headers["location"]
    if not nxt.startswith(f"{base}/"):
        # Dex shows a scope-approval page before redirecting back.
        nxt = str(r.url.join(nxt))
        r = await c.get(nxt)
        assert r.status_code == 200, r.text
        req = re.search(r'name="req" value="([^"]+)"', r.text) or re.search(
            r'name="req"[^>]+value="([^"]+)"', r.text
        )
        r = await c.post(
            str(r.url), data={"req": req.group(1), "approval": "approve"},
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        nxt = r.headers["location"]
    callback_url = str(r.url.join(nxt))
    assert callback_url.startswith(f"{base}/v1/auth/oidc/generic/callback")

    # Follow to the in-process app (mounted transport): token JSON.
    r = await c.get(callback_url)
    assert r.status_code == 200, r.text
    return r.json()


def test_oidc_code_flow_against_dex():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        app = __import__("agentrum.main", fromlist=["app"]).app
        base = "http://localhost:12122"
        async with httpx.AsyncClient(
            mounts={"all://localhost:12122": ASGITransport(app=app)},
            base_url="http://test",
            timeout=15,
        ) as c:
            body = await _drive_flow(c, base)
            # On a fresh database this is the JIT signup; on a reused one the
            # account exists — the no-duplicate property is pinned below.
            assert isinstance(body["created"], bool)
            assert body["user"]["username"], body  # JIT account from the IdP
            token = body["access_token"]

            # The minted session works on the REST surface.
            r = await c.get(f"{base}/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text
            assert r.json()["username"] == body["user"]["username"]

            # Second login: same identity, no duplicate account.
            body2 = await _drive_flow(c, base)
            assert body2["created"] is False, body2
            assert body2["user"]["id"] == body["user"]["id"]

    asyncio.run(inner())


def test_oidc_callback_rejects_forged_state():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        app = __import__("agentrum.main", fromlist=["app"]).app
        base = "http://localhost:12122"
        async with httpx.AsyncClient(
            mounts={"all://localhost:12122": ASGITransport(app=app)}, timeout=10
        ) as c:
            # A callback whose state does not match the cookie is refused —
            # no code exchange happens, forged or replayed callbacks die here.
            r = await c.get(
                f"{base}/v1/auth/oidc/generic/callback",
                params={"code": "x", "state": f"forged-{uuid.uuid4().hex}"},
            )
            assert r.status_code == 403, r.text

    asyncio.run(inner())
