"""Git-backed skills: resolve refs to commit SHAs at publish time and detect
upstream drift afterwards.

Uses dulwich (pure Python — no git binary required in the image). HTTPS
private repositories authenticate via a Secret resource holding
`username` / `password` (or token).
"""

import asyncio
import logging
import re
import socket
import threading
from contextlib import contextmanager, suppress
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import errors
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal
from agentrum.services import secret_service
from agentrum.services.conditions import merge_condition

logger = logging.getLogger("agentrum.git")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Skill entrypoint snapshots larger than this are rejected: the snapshot
# lives inside the immutable version's spec (JSONB), and skills are meant
# to be small instruction files.
_MAX_ENTRYPOINT_BYTES = 256 * 1024

# dulwich has no timeout parameter of its own, so the fetches below lean on
# socket.setdefaulttimeout — which is PROCESS-GLOBAL, not thread-local.
# Concurrent fetches would interleave capture/restore and leak a stale
# default timeout onto every other socket in the process. Holding one lock
# across the capture/restore window serializes the fetches and keeps the
# restore correct.
_SOCKET_TIMEOUT_LOCK = threading.Lock()


@contextmanager
def _socket_timeout(seconds: float):
    with _SOCKET_TIMEOUT_LOCK:
        previous = socket.getdefaulttimeout()
        socket.setdefaulttimeout(seconds)
        try:
            yield
        finally:
            socket.setdefaulttimeout(previous)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split a `---\\nYAML\\n---\\n` frontmatter block off a markdown file.
    Returns ({}, content) when no frontmatter is present."""
    import yaml

    if not content.startswith("---"):
        return {}, content
    lines = content.split("\n")
    if lines[0].strip() != "---":
        return {}, content
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "\n".join(lines[1:i])
            try:
                meta = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:
                raise errors.ValidationError(f"invalid frontmatter: {redact(exc)}") from exc
            if not isinstance(meta, dict):
                raise errors.ValidationError("frontmatter must be a YAML mapping")
            return meta, "\n".join(lines[i + 1:])
    return {}, content


def _snapshot_entrypoint_sync(
    url: str, sha: str, path: str, creds: tuple[str, str] | None
) -> dict:
    """Clone without checkout and read one file at an exact commit.
    Returns {path, content}. Repos are read-only in a temp dir."""
    import posixpath
    import tempfile

    from dulwich import porcelain
    from dulwich.objects import Blob, Tree

    kwargs: dict = {}
    if creds:
        kwargs = {"username": creds[0] or None, "password": creds[1]}
    with _socket_timeout(get_settings().git_timeout_seconds), tempfile.TemporaryDirectory(
        prefix="agentrum-skill-"
    ) as tmp:
        repo = porcelain.clone(url, tmp, checkout=False, **kwargs)
        store = repo.object_store
        tree: Tree = store[store[sha.encode()].tree]
        segments = [s for s in posixpath.normpath(path).split("/") if s not in ("", ".")]
        data: bytes | None = None
        for i, segment in enumerate(segments):
            entry = next((e for e in tree.items() if e.path.decode() == segment), None)
            if entry is None:
                raise errors.ValidationError(
                    f"entrypoint {path!r} not found in the repository at the pinned commit"
                )
            obj = store[entry.sha]
            if i == len(segments) - 1:
                if not isinstance(obj, Blob):
                    raise errors.ValidationError(f"entrypoint {path!r} is not a file")
                data = obj.data
            else:
                if not isinstance(obj, Tree):
                    raise errors.ValidationError(
                        f"entrypoint path {path!r} traverses a non-directory"
                    )
                tree = obj
    assert data is not None
    if len(data) > _MAX_ENTRYPOINT_BYTES:
        raise errors.ValidationError(
            f"entrypoint {path!r} is {len(data)} bytes; the snapshot cap is {_MAX_ENTRYPOINT_BYTES}"
        )
    return {"path": path, "content": data.decode("utf-8", errors="replace")}


def redact(text: str) -> str:
    """Strip any user:password userinfo from URLs embedded in error text so
    credentials decrypted from Secrets never reach API responses or logs."""
    return re.sub(r"(https?://)([^/@\s:]+):([^/@\s]+)@", r"\1\2:***@", str(text))


def _ls_remote_sync(url: str, ref: str, creds: tuple[str, str] | None) -> str:
    from dulwich import porcelain

    # Bound the socket wait; dulwich itself has no timeout parameter. The
    # process-global default is set/restored under _SOCKET_TIMEOUT_LOCK so
    # concurrent fetches cannot leak a stale value.
    kwargs = {}
    if creds:
        kwargs = {"username": creds[0] or None, "password": creds[1]}
    with _socket_timeout(get_settings().git_timeout_seconds):
        result = porcelain.ls_remote(url, **kwargs)
    # result.refs maps refname (bytes) -> sha (bytes); `.refs` is the current
    # dulwich API (dict-style access on the result is deprecated).
    refs = result.refs
    sha = _pick_ref(refs, ref)
    if sha is None:
        host = urlparse(url).hostname or url
        raise errors.ValidationError(f"git ref {ref!r} not found in remote ({host})")
    return sha.decode()


def _pick_ref(refs: dict, ref: str):  # type: ignore[no-untyped-def]
    """Resolve a ref to a sha. Exact matches only: a misspelled branch/tag
    must fail, never silently fall back to HEAD. Annotated tags resolve to
    the peeled commit sha when the remote advertises one."""
    wanted = f"refs/heads/{ref}".encode()
    if ref == "HEAD":
        return refs.get(b"HEAD")
    for candidate in (wanted, f"refs/tags/{ref}".encode()):
        sha = refs.get(candidate)
        if sha is not None:
            peeled = refs.get(candidate + b"^{}")  # annotated tag -> commit
            return peeled or sha
    short = ref.encode()
    sha = refs.get(short)
    if sha is not None:
        peeled = refs.get(short + b"^{}")
        return peeled or sha
    return None


async def _credentials_for(session: AsyncSession, namespace: str, credentials_ref: str | None):
    """Load (username, password) from a Secret resource, if referenced."""
    if not credentials_ref:
        return None
    from agentrum.services.resource_service import _get_resource

    secret = await _get_resource(session, "Secret", namespace, credentials_ref)
    if secret is None:
        raise errors.ValidationError(
            f"credentials_ref Secret {namespace}/{credentials_ref} not found"
        )
    payloads = await secret_service.get_payloads(session, secret.id)
    password = payloads.get("password") or payloads.get("token")
    if not password:
        raise errors.ValidationError(
            f"Secret {namespace}/{credentials_ref} needs a 'password' (or 'token') key"
        )
    return payloads.get("username") or "", password


async def resolve_git_source(session: AsyncSession, namespace: str, git: dict) -> dict:
    """Resolve a Skill's source.git to a pinned commit SHA.

    Returns the git dict augmented with `resolved_sha`. Failures raise
    ValidationError so a bad source can never be published ("no fake
    features" rule)."""
    url = (git.get("url") or "").strip()
    ref = (git.get("ref") or "HEAD").strip()
    if not url:
        raise errors.ValidationError("source.git.url is required")

    from agentrum.services import egress

    egress.validate_outbound_url(url, purpose="skill git source")

    resolved: dict = {"url": url, "ref": ref}
    if git.get("subdirectory"):
        resolved["subdirectory"] = git["subdirectory"]
    if git.get("credentials_ref"):
        resolved["credentials_ref"] = git["credentials_ref"]

    if _SHA_RE.fullmatch(ref):
        resolved["resolved_sha"] = ref  # already pinned by sha
        return resolved

    creds = await _credentials_for(session, namespace, git.get("credentials_ref"))
    try:
        sha = await asyncio.wait_for(
            asyncio.to_thread(_ls_remote_sync, url, ref, creds),
            timeout=get_settings().git_timeout_seconds + 5,
        )
    except errors.ValidationError:
        raise
    except Exception as exc:
        raise errors.ValidationError(
            f"cannot resolve git ref: {redact(exc)}"
        ) from exc
    resolved["resolved_sha"] = sha
    return resolved


async def snapshot_skill_entrypoint(
    session: AsyncSession, namespace: str, git: dict, resource_name: str,
    entrypoint: str | None = None,
) -> dict:
    """Read the skill's entrypoint file at the pinned commit and parse its
    YAML frontmatter.

    Returns {path, content, frontmatter}. The content snapshot makes the
    registry self-contained (the upstream repo can disappear; the published
    version still carries what it shipped). Follows the Anthropic skill
    format: when frontmatter exists, `name` must match the resource name and
    `description` is required — a catalog entry that disagrees with its own
    content is not publishable ("no fake features" rule)."""
    url = git["url"]
    sha = git["resolved_sha"]
    subdirectory = (git.get("subdirectory") or "").strip("/")
    entrypoint = (entrypoint or "SKILL.md").strip("/")
    path = f"{subdirectory}/{entrypoint}" if subdirectory else entrypoint

    creds = await _credentials_for(session, namespace, git.get("credentials_ref"))
    try:
        snapshot = await asyncio.wait_for(
            asyncio.to_thread(_snapshot_entrypoint_sync, url, sha, path, creds),
            timeout=get_settings().git_timeout_seconds + 30,
        )
    except errors.ValidationError:
        raise
    except Exception as exc:
        raise errors.ValidationError(
            f"cannot snapshot skill entrypoint: {redact(exc)}"
        ) from exc

    meta, _body = parse_frontmatter(snapshot["content"])
    if meta:
        fm_name = meta.get("name")
        if fm_name and str(fm_name) != resource_name:
            raise errors.ValidationError(
                f"frontmatter name {fm_name!r} does not match the resource name {resource_name!r}"
            )
        if not meta.get("description"):
            raise errors.ValidationError(
                f"entrypoint {path!r} has frontmatter but no description; "
                "skills need a description to be discoverable"
            )
    snapshot["frontmatter"] = meta
    return snapshot


async def check_drift_once(session: AsyncSession) -> int:
    """For git-sourced skills whose ref was a moving ref (branch/tag), check
    whether upstream moved. Writes an UpstreamDrift condition; never creates
    versions automatically (re-publishing pins the new SHA)."""
    if get_settings().skill_drift_interval_seconds <= 0:
        return 0

    rows = (
        await session.execute(
            select(models.Resource)
            .where(models.Resource.kind == "Skill", models.Resource.deleted_at.is_(None))
            .order_by(models.Resource.id)
        )
    ).scalars().all()
    if not rows:
        return 0

    from agentrum.services.resource_service import latest_versions

    latest = await latest_versions(session, [r.id for r in rows])

    checked = 0
    for resource in rows:
        rv = latest.get(resource.id)
        git = ((rv.spec or {}).get("source") or {}).get("git") if rv else None
        if not git or not git.get("resolved_sha") or _SHA_RE.fullmatch(git.get("ref", "")):
            continue  # not git-sourced, or pinned by explicit sha (cannot drift)
        try:
            creds = await _credentials_for(session, resource.namespace, git.get("credentials_ref"))
            upstream = await asyncio.wait_for(
                asyncio.to_thread(_ls_remote_sync, git["url"], git["ref"], creds),
                timeout=get_settings().git_timeout_seconds + 5,
            )
        except Exception as exc:  # noqa: BLE001 - unreachable remotes are logged, not fatal
            logger.warning(
                "skill drift check failed for %s/%s: %s",
                resource.namespace, resource.name, redact(exc),
            )
            continue
        checked += 1
        drifting = upstream != git["resolved_sha"]
        condition = {
            "type": "UpstreamDrift",
            "status": "True" if drifting else "False",
            "message": (
                f"upstream {git['ref']} moved: {git['resolved_sha'][:8]} -> {upstream[:8]} (re-publish to pin)"
                if drifting
                else f"upstream matches {upstream[:8]}"
            ),
        }
        merge_condition(resource, condition)
        # Commit per resource: a hang or failure on one skill must not hold a
        # transaction (or lose the results) for every other skill.
        await session.commit()
    return checked


async def run_forever() -> None:  # pragma: no cover - background loop
    interval = get_settings().skill_drift_interval_seconds
    if interval <= 0:
        logger.info("skill drift checker disabled (interval=0)")
        return
    logger.info("skill drift checker started (interval=%ss)", interval)
    while True:
        try:
            async with SessionLocal() as session:
                n = await check_drift_once(session)
                if n:
                    logger.info("checked %s git-sourced skill(s)", n)
        except Exception:
            logger.exception("skill drift tick failed")
        await asyncio.sleep(max(interval, 1))


def start_drift_checker() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_drift_checker(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
