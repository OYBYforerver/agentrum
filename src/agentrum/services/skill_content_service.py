"""Skill content delivery: serve the pinned tree of a git-backed skill as a
tarball to authorized consumers.

This closes the private-repo deadlock — the registry holds the fetch
credentials (decrypted server-side, never returned), consumers with read
access get the bytes at the locked commit. The tarball is built from git
tree objects directly, with no working-tree checkout: subdirectory
traversal and symlinks cannot escape the pinned tree, and submodule
gitlinks (whose content is not in this repository) are skipped.
"""

import asyncio
import io
import posixpath
import socket
import tarfile
import tempfile

from agentrum import errors
from agentrum.config import get_settings
from agentrum.db import models


def _validate_subdirectory(sub: str | None) -> list[str]:
    """Return path segments for a subdirectory confined to the repo root."""
    if not sub:
        return []
    norm = posixpath.normpath(sub.strip())
    if posixpath.isabs(norm) or norm == ".." or norm.startswith("../"):
        raise errors.ValidationError("subdirectory must be a relative path inside the repository")
    return [s for s in norm.split("/") if s not in ("", ".")]


def _build_tarball_sync(
    url: str, sha: str, subdirectory: list[str], creds: tuple[str, str] | None, max_bytes: int
) -> bytes:
    from dulwich import porcelain
    from dulwich.objects import Blob, Tree

    settings = get_settings()
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(settings.git_timeout_seconds)
        kwargs: dict = {}
        if creds:
            kwargs = {"username": creds[0] or None, "password": creds[1]}
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory(prefix="agentrum-skill-content-") as tmp:
            repo = porcelain.clone(url, tmp, checkout=False, **kwargs)
            store = repo.object_store
            try:
                commit = store[sha.encode()]
            except KeyError:
                raise errors.ValidationError(
                    f"commit {sha[:12]} not found in the skill's source repository"
                ) from None
            tree: Tree = store[commit.tree]

            for segment in subdirectory:
                entry = next((e for e in tree.items() if e.path.decode() == segment), None)
                if entry is None:
                    raise errors.ValidationError(
                        f"subdirectory {('/'.join(subdirectory))!r} not found at the pinned commit"
                    )
                obj = store[entry.sha]
                if not isinstance(obj, Tree):
                    raise errors.ValidationError(
                        f"subdirectory path traverses a non-directory at {segment!r}"
                    )
                tree = obj

            total = 0

            with tarfile.open(fileobj=buf, mode="w:gz") as tar:

                def walk(tree: Tree, prefix: str) -> None:
                    nonlocal total
                    for entry in tree.items():
                        path = f"{prefix}{entry.path.decode()}"
                        obj = store[entry.sha]
                        if isinstance(obj, Tree):
                            info = tarfile.TarInfo(path)
                            info.type = tarfile.DIRTYPE
                            info.mode = 0o755
                            tar.addfile(info)
                            walk(obj, f"{path}/")
                        elif isinstance(obj, Blob):
                            data = obj.data
                            total += len(data)
                            if total > max_bytes:
                                raise errors.ValidationError(
                                    f"skill content exceeds the {max_bytes // (1024 * 1024)} MiB cap"
                                )
                            info = tarfile.TarInfo(path)
                            info.size = len(data)
                            info.mode = 0o755 if entry.mode & 0o111 else 0o644
                            tar.addfile(info, io.BytesIO(data))
                        # gitlinks (submodules) are skipped: the pinned tree
                        # does not contain their content.

                walk(tree, "")
    finally:
        socket.setdefaulttimeout(previous_timeout)
    return buf.getvalue()


async def build_tarball(
    session, resource: models.Resource, version  # type: ignore[no-untyped-def]
) -> tuple[bytes, str]:
    """Build a gzipped tarball of the skill's tree at the version's pinned
    commit. Returns (tarball_bytes, sha). Raises ValidationError for anything
    unfetchable — inline-only skills, unpinned versions, blocked or
    unreachable sources, oversized content."""
    from agentrum.services import egress
    from agentrum.services.git_service import _credentials_for, redact

    spec = (version.spec or {}) if version is not None else {}
    git = ((spec.get("source") or {}).get("git")) or None
    if not git:
        raise errors.ValidationError(
            "this skill has no git source; inline instructions ship in the resource spec"
        )
    url = (git.get("url") or "").strip()
    sha = (git.get("resolved_sha") or "").strip()
    if not url or not sha:
        raise errors.ValidationError("skill version is missing a pinned commit")

    egress.validate_outbound_url(url, purpose="skill content fetch")
    creds = await _credentials_for(session, resource.namespace, git.get("credentials_ref"))
    subdirectory = _validate_subdirectory(git.get("subdirectory"))
    settings = get_settings()
    try:
        blob = await asyncio.wait_for(
            asyncio.to_thread(
                _build_tarball_sync, url, sha, subdirectory, creds, settings.skill_content_max_bytes
            ),
            timeout=settings.git_timeout_seconds + 30,
        )
    except errors.ValidationError:
        raise
    except Exception as exc:
        raise errors.ValidationError(f"cannot fetch skill content: {redact(exc)}") from exc
    return blob, sha
