"""Git-backed skill sources: publish-time SHA pinning and drift detection."""

import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(
        __import__("os").environ.get("ARK_INTEGRATION") != "1",
        reason="integration tests require ARK_INTEGRATION=1 and a test database",
    ),
]


def _suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def local_skill_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "skills-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "SKILL.md").write_text("# gateway skill\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_publish_pins_commit_sha_and_detects_drift(local_skill_repo: Path):  # pragma: no cover
    """Publish a git-sourced skill against a local repo: the version spec must
    carry the resolved commit SHA; after HEAD moves, the drift check flags
    UpstreamDrift."""
    import asyncio

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin
    from agentrum.services.git_service import check_drift_once

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            team = f"git-skill-{sfx}"
            r = await c.post("/v1/teams", headers=admin, json={"name": team})
            assert r.status_code == 201, r.text

            url = f"file://{local_skill_repo}"
            r = await c.put(
                f"/v1/resources/Skill/{team}/gateway-skill",
                headers=admin,
                json={
                    "spec": {"source": {"git": {"url": url, "ref": "HEAD"}}},
                    "tag": "v1.0.0",
                },
            )
            assert r.status_code == 201, r.text
            spec = r.json()["latest_version"]["spec"]
            sha = spec["source"]["git"]["resolved_sha"]
            assert len(sha) == 40, spec

            # HEAD moves → drift check must flag it
            (local_skill_repo / "SKILL.md").write_text("# gateway skill v2\n")
            _git(local_skill_repo, "add", "-A")
            _git(local_skill_repo, "commit", "-q", "-m", "v2")

            from agentrum.db.engine import SessionLocal

            async with SessionLocal() as session:
                n = await check_drift_once(session)
                assert n >= 1

            r = await c.get(f"/v1/resources/Skill/{team}/gateway-skill", headers=admin)
            conds = (r.json().get("status") or {}).get("conditions", [])
            drift = [x for x in conds if x["type"] == "UpstreamDrift"]
            assert drift and drift[0]["status"] == "True", r.json()
            assert "->" in drift[0]["message"]

    asyncio.run(inner())
