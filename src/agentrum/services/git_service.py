"""Git-backed skills: resolve refs to commit SHAs at publish time and detect
upstream drift afterwards.

Uses dulwich (pure Python — no git binary required in the image). HTTPS
private repositories authenticate via a Secret resource holding
`username` / `password` (or token).
"""

import asyncio
import logging
import re
from contextlib import suppress
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import errors
from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal
from agentrum.services import secret_service

logger = logging.getLogger("agentrum.git")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _with_credentials(url: str, username: str, password: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return url  # local paths / ssh are used as-is
    return urlunparse(parsed._replace(netloc=f"{username}:{password}@{parsed.netloc}"))


def _ls_remote_sync(url: str, ref: str) -> str:
    from dulwich import porcelain

    refs = porcelain.ls_remote(url)  # dict: bytes refname -> bytes sha
    wanted = f"refs/heads/{ref}".encode()
    tags = f"refs/tags/{ref}".encode()
    for candidate in (wanted, tags, b"HEAD"):
        if candidate in refs:
            return refs[candidate].decode()
    key = ref.encode()
    if key in refs:
        return refs[key].decode()
    host = urlparse(url).hostname or url
    raise errors.ValidationError(f"git ref {ref!r} not found in remote ({host})")


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

    resolved: dict = {"url": url, "ref": ref}
    if git.get("subdirectory"):
        resolved["subdirectory"] = git["subdirectory"]
    if git.get("credentials_ref"):
        resolved["credentials_ref"] = git["credentials_ref"]

    if _SHA_RE.fullmatch(ref):
        resolved["resolved_sha"] = ref  # already pinned by sha
        return resolved

    creds = await _credentials_for(session, namespace, git.get("credentials_ref"))
    remote_url = _with_credentials(url, *creds) if creds else url
    try:
        sha = await asyncio.to_thread(_ls_remote_sync, remote_url, ref)
    except errors.ValidationError:
        raise
    except Exception as exc:
        raise errors.ValidationError(f"cannot resolve git ref: {exc}") from exc
    resolved["resolved_sha"] = sha
    return resolved


async def check_drift_once(session: AsyncSession) -> int:
    """For git-sourced skills whose ref was a moving ref (branch/tag), check
    whether upstream moved. Writes an UpstreamDrift condition; never creates
    versions automatically (re-publishing pins the new SHA)."""
    if get_settings().skill_drift_interval_seconds <= 0:
        return 0

    rows = (
        await session.execute(
            select(models.Resource).where(
                models.Resource.kind == "Skill", models.Resource.deleted_at.is_(None)
            )
        )
    ).scalars().all()
    if not rows:
        return 0

    latest: dict = {}
    versions = (
        await session.execute(
            select(models.ResourceVersion)
            .where(models.ResourceVersion.resource_id.in_([r.id for r in rows]))
            .order_by(models.ResourceVersion.version.desc())
        )
    ).scalars().all()
    for rv in versions:
        latest.setdefault(rv.resource_id, rv)

    checked = 0
    for resource in rows:
        rv = latest.get(resource.id)
        git = ((rv.spec or {}).get("source") or {}).get("git") if rv else None
        if not git or not git.get("resolved_sha") or _SHA_RE.fullmatch(git.get("ref", "")):
            continue  # not git-sourced, or pinned by explicit sha (cannot drift)
        try:
            creds = await _credentials_for(session, resource.namespace, git.get("credentials_ref"))
            remote_url = _with_credentials(git["url"], *creds) if creds else git["url"]
            upstream = await asyncio.to_thread(_ls_remote_sync, remote_url, git["ref"])
        except Exception as exc:  # noqa: BLE001 - unreachable remotes are logged, not fatal
            logger.warning("skill drift check failed for %s/%s: %s", resource.namespace, resource.name, exc)
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
        if (resource.status or {}).get("conditions") != [condition]:
            resource.status = {"conditions": [condition]}
    await session.commit()
    return checked


async def run_forever() -> None:  # pragma: no cover - background loop
    interval = get_settings().skill_drift_interval_seconds
    logger.info("skill drift checker started (interval=%ss)", interval)
    while True:
        try:
            async with SessionLocal() as session:
                n = await check_drift_once(session)
                if n:
                    logger.info("checked %s git-sourced skill(s)", n)
        except Exception:
            logger.exception("skill drift tick failed")
        await asyncio.sleep(interval)


def start_drift_checker() -> asyncio.Task:
    return asyncio.create_task(run_forever())


async def stop_drift_checker(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
