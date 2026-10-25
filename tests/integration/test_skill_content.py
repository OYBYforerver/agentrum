"""Skill content delivery: authorized consumers get the pinned tree as a
tarball; visibility rules apply; inline-only skills and non-Skill kinds are
rejected with clear errors."""

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(
        __import__("os").environ.get("ARK_INTEGRATION") != "1",
        reason="integration tests require ARK_INTEGRATION=1 and a test database",
    ),
]


def _suffix():
    import uuid

    return uuid.uuid4().hex[:8]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def skill_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "skills-repo"
    (repo / "pack" / "gateway").mkdir(parents=True)
    (repo / "pack" / "gateway" / "SKILL.md").write_text("# payment skill\n")
    (repo / "SKILL.md").write_text("# repo root skill\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _tar_names(blob: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return sorted(m.name for m in tar.getmembers())


def _tar_read(blob: bytes, name: str) -> str:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return tar.extractfile(name).read().decode()


def test_skill_content_delivery_end_to_end(skill_repo: Path):  # pragma: no cover
    import asyncio

    import httpx
    from httpx import ASGITransport

    from agentrum.main import _ensure_bootstrap_admin

    async def inner():
        await _ensure_bootstrap_admin()
        sfx = _suffix()
        owner, outsider = f"ct-own-{sfx}", f"ct-out-{sfx}"
        async with httpx.AsyncClient(
            transport=ASGITransport(app=__import__("agentrum.main", fromlist=["app"]).app),
            base_url="http://test",
        ) as c:
            r = await c.post("/v1/auth/login", json={"username": "admin", "password": "admin123"})
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
            for t in (owner, outsider):
                r = await c.post("/v1/teams", headers=admin, json={"name": t})
                assert r.status_code == 201, r.text

            # Public (internal-visibility) git skill with a subdirectory.
            r = await c.put(
                f"/v1/resources/Skill/{owner}/pay-skill",
                headers=admin,
                json={
                    "spec": {
                        "source": {
                            "git": {
                                "url": f"file://{skill_repo}",
                                "ref": "HEAD",
                                "subdirectory": "pack/gateway",
                            }
                        }
                    },
                    "tag": "v1.0.0",
                    "visibility": "internal",
                },
            )
            assert r.status_code == 201, r.text
            sha = r.json()["latest_version"]["spec"]["source"]["git"]["resolved_sha"]

            # Owner project: full tree of the subdirectory at the pinned SHA.
            r = await c.get(f"/v1/resources/Skill/{owner}/pay-skill/content", headers=admin)
            assert r.status_code == 200, r.text
            assert r.headers["x-agentrum-sha"] == sha
            assert _tar_names(r.content) == ["SKILL.md"]
            assert _tar_read(r.content, "SKILL.md") == "# payment skill\n"

            # Pinned tag keeps serving the pinned tree even after HEAD moves.
            (skill_repo / "pack" / "gateway" / "SKILL.md").write_text("# changed upstream\n")
            _git(skill_repo, "add", "-A")
            _git(skill_repo, "commit", "-q", "-m", "v2")
            r = await c.get(f"/v1/resources/Skill/{owner}/pay-skill/content", headers=admin)
            assert r.status_code == 200, r.text
            assert _tar_read(r.content, "SKILL.md") == "# payment skill\n"

            # Inline-only skills decline with a pointer to the spec.
            r = await c.put(
                f"/v1/resources/Skill/{owner}/inline-skill",
                headers=admin,
                json={"spec": {"instructions": "be helpful"}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            r = await c.get(f"/v1/resources/Skill/{owner}/inline-skill/content", headers=admin)
            assert r.status_code == 400, r.text
            assert "inline" in r.json()["detail"].lower(), r.text

            # Only Skills have content.
            r = await c.get(f"/v1/resources/Skill/{owner}/nope/content", headers=admin)
            assert r.status_code == 404, r.text
            r = await c.put(
                f"/v1/resources/Prompt/{owner}/p1",
                headers=admin,
                json={"spec": {"template": "hi"}, "tag": "v1"},
            )
            assert r.status_code == 201, r.text
            r = await c.get(f"/v1/resources/Prompt/{owner}/p1/content", headers=admin)
            assert r.status_code == 400, r.text

            # Restricted visibility: an outsider without an approved
            # subscription cannot fetch the bytes.
            r = await c.put(
                f"/v1/resources/Skill/{owner}/private-skill",
                headers=admin,
                json={
                    "spec": {"source": {"git": {"url": f"file://{skill_repo}", "ref": "HEAD"}}},
                    "tag": "v1",
                    "visibility": "restricted",
                },
            )
            assert r.status_code == 201, r.text
            r = await c.post("/v1/users", headers=admin, json={"username": f"ct-u-{sfx}", "password": "password-123"})
            assert r.status_code == 201, r.text
            r = await c.post(
                f"/v1/teams/{outsider}/members", headers=admin,
                json={"username": f"ct-u-{sfx}", "role": "developer"},
            )
            assert r.status_code == 201, r.text
            r = await c.post("/v1/auth/login", json={"username": f"ct-u-{sfx}", "password": "password-123"})
            outsider_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await c.get(f"/v1/resources/Skill/{owner}/private-skill/content", headers=outsider_headers)
            assert r.status_code in (403, 404), r.text
            # …while the internal one stays readable to them.
            r = await c.get(f"/v1/resources/Skill/{owner}/pay-skill/content", headers=outsider_headers)
            assert r.status_code == 200, r.text

    asyncio.run(inner())
