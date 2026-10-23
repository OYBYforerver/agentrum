"""Deployment controller: a level-triggered reconciler over the Postgres
desired state, driving a pluggable runtime adapter — the same pattern the
upstream Go project uses, rebuilt for Python."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal
from agentrum.services import secret_service
from agentrum.services.deployments.adapter import DeploymentAdapter, DeploymentPlan, get_adapter
from agentrum.services.deployments.allowlist import image_allowed, parse_allowlist

logger = logging.getLogger("agentrum.deploy")


def _condition(ok: bool, message: str, reason: str = "Reconciled") -> dict:
    return {
        "type": "Ready",
        "status": "True" if ok else "False",
        "reason": reason,
        "message": message,
        "last_transition": datetime.now(UTC).isoformat(timespec="seconds"),
    }


async def _latest_versions(session, ids: list) -> dict:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(models.ResourceVersion)
            .where(models.ResourceVersion.resource_id.in_(ids))
            .order_by(models.ResourceVersion.version.desc())
        )
    ).scalars().all()
    latest: dict = {}
    for rv in rows:
        latest.setdefault(rv.resource_id, rv)
    return latest


async def _tagged_version(session, resource_id, tag: str) -> models.ResourceVersion | None:
    return (
        await session.execute(
            select(models.ResourceVersion).where(
                models.ResourceVersion.resource_id == resource_id,
                models.ResourceVersion.tag == tag,
            )
        )
    ).scalars().first()


async def reconcile_tick(session, adapter: DeploymentAdapter) -> int:
    """One reconciliation pass. Returns the number of adapter actions taken."""
    settings = get_settings()
    allowlist = parse_allowlist(settings.image_allowlist)

    rows = (
        await session.execute(
            select(models.Resource)
            .where(models.Resource.kind == "Deployment")
            .limit(100)
        )
    ).scalars().all()
    if not rows:
        return 0
    latest = await _latest_versions(session, [r.id for r in rows])

    from agentrum.services.resource_service import _get_resource

    actions = 0
    for row in rows:
        rv = latest.get(row.id)
        if rv is None:
            continue
        spec = rv.spec or {}
        condition: dict | None = None

        if row.deleted_at is not None:
            plan = _plan_from(row, spec, image="", env={})
            try:
                condition = await adapter.remove(plan)
            except Exception as exc:  # noqa: BLE001 - surface adapter failures as conditions
                condition = _condition(False, f"adapter error: {exc}", reason="AdapterError")
            actions += 1
        else:
            target = await _get_resource(
                session, spec["target_kind"], spec["target_namespace"], spec["target_name"]
            )
            if target is None:
                condition = _condition(False, "deployment target not found", reason="TargetMissing")
            else:
                image_rv = (
                    await _tagged_version(session, target.id, spec["tag"])
                    if spec.get("tag")
                    else (await _latest_versions(session, [target.id])).get(target.id)
                )
                image = (image_rv.spec or {}).get("image") if image_rv else None
                if not image:
                    condition = _condition(
                        False, "target resource has no image to run", reason="NoImage"
                    )
                elif not image_allowed(image, allowlist):
                    condition = _condition(
                        False,
                        f"image {image!r} rejected by ARK_IMAGE_ALLOWLIST",
                        reason="ImageNotAllowed",
                    )
                else:
                    try:
                        env = await secret_service.resolve_env(
                            session,
                            (image_rv.spec or {}).get("env") or [],
                            default_namespace=spec["target_namespace"],
                        )
                    except Exception as exc:  # noqa: BLE001 - unresolvable refs surface as conditions
                        condition = _condition(False, str(exc), reason="EnvResolutionFailed")
                    else:
                        plan = _plan_from(row, spec, image=image, env=env)
                        try:
                            condition = await adapter.apply(plan)
                        except Exception as exc:  # noqa: BLE001 - surfaced as a condition
                            condition = _condition(
                                False, f"adapter error: {exc}", reason="AdapterError"
                            )
                        actions += 1

        if condition and (row.status or {}).get("conditions") != [condition]:
            row.status = {"conditions": [condition]}
    await session.commit()
    return actions


def _plan_from(row: models.Resource, spec: dict, image: str, env: dict) -> DeploymentPlan:
    return DeploymentPlan(
        name=f"{row.namespace}-{row.name}",
        cluster_namespace=spec.get("cluster_namespace") or "default",
        image=image,
        env=env,
        replicas=spec.get("replicas", 1),
        image_pull_policy=spec.get("image_pull_policy", "IfNotPresent"),
        port=spec.get("port", 8000),
    )


async def run_forever(adapter: DeploymentAdapter | None = None) -> None:  # pragma: no cover
    adapter = adapter or get_adapter("kubernetes")
    interval = get_settings().deploy_interval_seconds
    logger.info("deployment controller started (interval=%ss)", interval)
    while True:
        try:
            async with SessionLocal() as session:
                n = await reconcile_tick(session, adapter)
                if n:
                    logger.info("reconciled %s deployment(s)", n)
        except Exception:
            logger.exception("deployment reconcile tick failed")
        await asyncio.sleep(interval)


def start_controller(adapter: DeploymentAdapter | None = None) -> asyncio.Task:
    return asyncio.create_task(run_forever(adapter))


async def stop_controller(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
