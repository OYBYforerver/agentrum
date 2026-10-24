"""Integration tests for the content-model adaptations (publish flows).

Gate: ARK_INTEGRATION=1 plus ARK_DATABASE_URL pointing at a dedicated test
database (same as test_flow.py).
"""

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def local_skill_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "skills-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "SKILL.md").write_text(
        "---\nname: gateway-skill\ndescription: Routes payments through the gateway\n---\n"
        "# gateway skill\nUse this skill to route payments.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


async def _admin(c):
    r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_skill_publish_snapshots_entrypoint_frontmatter(local_skill_repo: Path):  # pragma: no cover
    """Publishing a git-backed skill snapshots SKILL.md (with parsed
    frontmatter) into the immutable version."""
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            admin = await _admin(c)
            team = f"cm-skill-{sfx}"
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text

            r = await c.put(
                f"/v1/resources/Skill/{team}/gateway-skill", headers=admin,
                json={"spec": {"source": {"git": {"url": f"file://{local_skill_repo}", "ref": "HEAD"}}},
                      "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            spec = r.json()["latest_version"]["spec"]
            snap = spec["entrypoint_snapshot"]
            assert snap["path"] == "SKILL.md"
            assert snap["frontmatter"]["name"] == "gateway-skill"
            assert "route payments" in snap["content"]
            assert spec["source"]["git"]["resolved_sha"]

            # name mismatch between frontmatter and resource name must fail
            r = await c.put(
                f"/v1/resources/Skill/{team}/other-name", headers=admin,
                json={"spec": {"source": {"git": {"url": f"file://{local_skill_repo}", "ref": "HEAD"}}}},
            )
            assert r.status_code == 400, r.text
            assert "does not match" in r.text

    _run(inner())


def test_deprecation_flow_notifies_subscribers():  # pragma: no cover
    """PATCH deprecated=true marks the resource, enqueues subscriber
    notifications; deprecated=false clears it."""
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            admin = await _admin(c)
            team = f"cm-dep-{sfx}"
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text
            r = await c.put(
                f"/v1/resources/Agent/{team}/legacy", headers=admin,
                json={"spec": {"image": "reg/legacy:1"}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text

            # a second team subscribes (internal → active immediately)
            sub = f"cm-dep-sub-{sfx}"
            r = await c.post("/v1/teams", headers=admin, json={"name": sub})
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{sub}/subscriptions", headers=admin,
                json={"kind": "Agent", "namespace": team, "name": "legacy"},
            )
            assert r.status_code == 201, r.text
            assert r.json()["status"] == "active", r.text

            r = await c.patch(
                f"/v1/resources/Agent/{team}/legacy", headers=admin,
                json={"deprecated": True, "deprecation_reason": "superseded",
                      "successor": f"{team}/legacy-v2"},
            )
            assert r.status_code == 200, r.text
            dep = r.json()["deprecation"]
            assert dep is not None and dep["reason"] == "superseded"
            assert dep["successor"].endswith("/legacy-v2")

            # a subscriber notification was enqueued
            from sqlalchemy import select

            from agentrum.db import models as m
            from agentrum.db.engine import SessionLocal

            async with SessionLocal() as session:
                rows = (
                    await session.execute(
                        select(m.NotificationOutbox).where(
                            m.NotificationOutbox.event_type == "resource.deprecated"
                        )
                    )
                ).scalars().all()
                assert any(r.payload["name"] == "legacy" for r in rows)

            # undeprecate clears the marker
            r = await c.patch(
                f"/v1/resources/Agent/{team}/legacy", headers=admin,
                json={"deprecated": False},
            )
            assert r.status_code == 200, r.text
            assert r.json()["deprecation"] is None

    _run(inner())


def test_connect_endpoint_and_schema_endpoint():  # pragma: no cover
    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as c:
            admin = await _admin(c)
            team = f"cm-mcp-{sfx}"
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text
            r = await c.put(
                f"/v1/resources/MCPServer/{team}/weather", headers=admin,
                json={"spec": {"transport": "stdio", "command": "npx",
                               "args": ["-y", "@mcp/weather"], "tag": "v1"}},
            )
            assert r.status_code == 201, r.text

            r = await c.get(f"/v1/resources/MCPServer/{team}/weather/connect", headers=admin)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["stdio"]["args"] == ["-y", "@mcp/weather"]
            assert "claude mcp add weather" in body["clients"]["claude_code"]

            # non-MCP kinds are rejected
            r = await c.put(
                f"/v1/resources/Agent/{team}/plain", headers=admin,
                json={"spec": {"image": "reg/a:1"}},
            )
            assert r.status_code == 201, r.text
            r = await c.get(f"/v1/resources/Agent/{team}/plain/connect", headers=admin)
            assert r.status_code == 400, r.text

            # manifest schema is public and shaped for editors
            r = await c.get("/v1/schema/manifest.json")
            assert r.status_code == 200, r.text
            schema = r.json()
            assert set(schema["$defs"]) >= {"AgentSpec", "MCPServerSpec", "SkillSpec"}
            assert set(schema["properties"]["kind"]["enum"]) >= {"Agent", "Secret"}

    _run(inner())
