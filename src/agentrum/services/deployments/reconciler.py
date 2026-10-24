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
from agentrum.services.deployments.allowlist import (
    image_allowed,
    parse_allowlist,
    warn_if_permissive,
)

logger = logging.getLogger("agentrum.deploy")


def _condition(ok: bool, message: str, reason: str = "Reconciled") -> dict:
    return {
        "type": "Ready",
        "status": "True" if ok else "False",
        "reason": reason,
        "message": message,
        "last_transition": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _conditions_equal(a: dict | None, b: dict | None) -> bool:
    """Condition comparison that ignores the timestamp, so an unchanged state
    does not rewrite the row (and updated_at) every tick."""
    if a is None or b is None:
        return a is b
    a, b = dict(a), dict(b)
    a.pop("last_transition", None)
    b.pop("last_transition", None)
    return a == b


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
            .order_by(models.Resource.id)  # deterministic: no starvation
            .limit(100)
        )
    ).scalars().all()
    if not rows:
        return 0

    from agentrum.services.resource_service import _get_resource, latest_versions

    latest = await latest_versions(session, [r.id for r in rows])

    actions = 0
    for row in rows:
        rv = latest.get(row.id)
        if rv is None:
            continue
        spec = rv.spec or {}
        status = dict(row.status or {})
        condition: dict | None = None

        if row.deleted_at is not None:
            if status.get("removed"):
                continue  # terminal state: cluster is clean, nothing more to do
            plan = _plan_from(row, spec, image="", env={})
            try:
                condition = await adapter.remove(plan)
                status["removed"] = True
            except Exception as exc:  # noqa: BLE001 - surface adapter failures as conditions
                logger.warning("remove failed for %s/%s: %s", row.namespace, row.name, exc)
                condition = _condition(False, "adapter failed to remove the workload", reason="AdapterError")
            actions += 1
        else:
            target_kind = spec.get("target_kind")
            target_namespace = spec.get("target_namespace")
            target_name = spec.get("target_name")
            if not (target_kind and target_namespace and target_name):
                condition = _condition(
                    False, "deployment spec is missing its target reference", reason="InvalidSpec"
                )
            else:
                target = await _get_resource(session, target_kind, target_namespace, target_name)
                if target is None:
                    condition = _condition(False, "deployment target not found", reason="TargetMissing")
                else:
                    image_rv = (
                        await _tagged_version(session, target.id, spec["tag"])
                        if spec.get("tag")
                        else (await latest_versions(session, [target.id])).get(target.id)
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
                                default_namespace=target_namespace,
                            )
                        except Exception as exc:  # noqa: BLE001
                            # The raw error may name other namespaces' secrets;
                            # keep it server-side, publish a stable message.
                            logger.warning(
                                "env resolution failed for %s/%s: %s", row.namespace, row.name, exc
                            )
                            condition = _condition(
                                False,
                                "environment could not be resolved (check secretRefs)",
                                reason="EnvResolutionFailed",
                            )
                        else:
                            plan = _plan_from(row, spec, image=image, env=env)
                            try:
                                condition = await adapter.apply(plan)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "apply failed for %s/%s: %s", row.namespace, row.name, exc
                                )
                                condition = _condition(
                                    False, "adapter failed to apply the workload", reason="AdapterError"
                                )
                            actions += 1

        if condition and not _conditions_equal(
            (row.status or {}).get("conditions", [None])[0], condition
        ):
            status["conditions"] = [condition]
            row.status = status
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
    warn_if_permissive(parse_allowlist(get_settings().image_allowlist))
    logger.info("deployment controller started (interval=%ss)", interval)
    while True:
        try:
            async with SessionLocal() as session:
                n = await reconcile_tick(session, adapter)
                if n:
                    logger.info("reconciled %s deployment(s)", n)
        except Exception:
            logger.exception("deployment reconcile tick failed")
        await asyncio.sleep(max(interval, 1))


def start_controller(adapter: DeploymentAdapter | None = None) -> asyncio.Task:
    return asyncio.create_task(run_forever(adapter))


async def stop_controller(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
