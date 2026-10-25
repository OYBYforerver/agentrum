"""MCP prompt surface: list_prompts / get_prompt behave like the rest of the
tool surface — per-caller visibility (prompts are project-private), template
fetch, validated rendering."""

import asyncio
import json
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


class _McpCtx:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_mcp_prompt_tools(tmp_path):  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin
    from agentrum.mcp_server import get_prompt, list_prompts

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        team, other = f"pm-{sfx}", f"pm-other-{sfx}"
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text
            r = await c.put(
                f"/v1/resources/Prompt/{team}/review-style",
                headers=admin,
                json={
                    "spec": {
                        "template": "Review this {{ language }} code in {{ style }} tone.",
                        "variables": [
                            {"name": "language", "required": True},
                            {"name": "style", "required": False, "description": "tone"},
                        ],
                    },
                    "tag": "v1",
                    "description": "code review prompt",
                },
            )
            assert r.status_code == 201, r.text

            admin_ctx = _McpCtx(dict(admin))

            # list_prompts: entry with declared variables
            listed = json.loads(await list_prompts(admin_ctx))
            entries = [e for e in listed if e["ref"] == f"Prompt/{team}/review-style"]
            assert entries and entries[0]["variables"][0]["name"] == "language"

            # get_prompt without values: template + variables
            fetched = json.loads(await get_prompt(admin_ctx, f"Prompt/{team}/review-style"))
            assert "Review this {{ language }}" in fetched["template"]
            assert {v["name"] for v in fetched["variables"]} == {"language", "style"}

            # with values: rendered
            rendered = await get_prompt(
                admin_ctx, f"Prompt/{team}/review-style",
                variables_json=json.dumps({"language": "python", "style": "blunt"}),
            )
            assert rendered == "Review this python code in blunt tone."

            # required variable missing → explicit error
            from agentrum import errors as ark_errors

            with pytest.raises(ark_errors.ValidationError):
                await get_prompt(
                    admin_ctx, f"Prompt/{team}/review-style",
                    variables_json=json.dumps({"style": "blunt"}),
                )

            # project privacy: an outsider neither lists nor fetches
            r = await c.post("/v1/teams", headers=admin, json={"name": other})
            assert r.status_code == 201, r.text
            r = await c.post(
                "/v1/users", headers=admin,
                json={"username": f"pm-u-{sfx}", "password": "password-123"},
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{other}/members", headers=admin,
                json={"username": f"pm-u-{sfx}", "role": "developer"},
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                "/v1/auth/login", json={"username": f"pm-u-{sfx}", "password": "password-123"}
            )
            outsider_ctx = _McpCtx({"Authorization": f"Bearer {r.json()['access_token']}"})

            listed = json.loads(await list_prompts(outsider_ctx))
            assert f"Prompt/{team}/review-style" not in [e["ref"] for e in listed]
            with pytest.raises(Exception):  # noqa: B017 - permission denial shape is the server's
                await get_prompt(outsider_ctx, f"Prompt/{team}/review-style")

    asyncio.run(inner())
