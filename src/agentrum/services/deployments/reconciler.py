"""Deployment controller: a level-triggered reconciler over the Postgres
desired state, driving a pluggable runtime adapter — the same pattern the
upstream Go project uses, rebuilt for Python."""

import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select

from agentrum.config import get_settings
from agentrum.db import models
from agentrum.db.engine import SessionLocal
from agentrum.services import secret_service
from agentrum.services.conditions import merge_condition
from agentrum.services.deployments.adapter import DeploymentAdapter, DeploymentPlan, get_adapter
from agentrum.services.deployments.allowlist import (
    image_allowed,
    parse_allowlist,
    warn_if_permissive,
)

logger = logging.getLogger("agentrum.deploy")

# Rows processed per query round; every Deployment resource still gets its
# turn thanks to keyset pagination (see reconcile_tick).
_RECONCILE_BATCH = 100


def _condition(ok: bool, message: str, reason: str = "Reconciled") -> dict:
    return {
        "type": "Ready",
        "status": "True" if ok else "False",
        "reason": reason,
        "message": message,
        "last_transition": datetime.now(UTC).isoformat(timespec="seconds"),
    }


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
    """One reconciliation pass over EVERY Deployment resource (keyset
    pagination — a plain limit would starve everything past the first page
    once the table grows). Returns the number of adapter actions taken."""
    settings = get_settings()
    allowlist = parse_allowlist(settings.image_allowlist)

    from agentrum.services.resource_service import _get_resource, latest_versions

    actions = 0
    cursor: uuid.UUID | None = None
    while True:
        stmt = select(models.Resource).where(models.Resource.kind == "Deployment")
        if cursor is not None:
            stmt = stmt.where(models.Resource.id > cursor)
        rows = (await session.execute(stmt.order_by(models.Resource.id).limit(_RECONCILE_BATCH))).scalars().all()
        if not rows:
            break
        cursor = rows[-1].id

        latest = await latest_versions(session, [r.id for r in rows])

        for row in rows:
            rv = latest.get(row.id)
            if rv is None:
                continue
            spec = rv.spec or {}
            condition: dict | None = None

            if row.deleted_at is not None:
                if (row.status or {}).get("removed"):
                    continue  # terminal state: cluster is clean, nothing more to do
                plan = _plan_from(row, spec, image="", env={})
                try:
                    condition = await adapter.remove(plan)
                    row.status = {**(row.status or {}), "removed": True}
                except Exception as exc:  # noqa: BLE001 - surface adapter failures as conditions
                    logger.warning("remove failed for %s/%s: %s", row.namespace, row.name, exc)
                    condition = _condition(
                        False, "adapter failed to remove the workload", reason="AdapterError"
                    )
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
                        condition = _condition(
                            False, "deployment target not found", reason="TargetMissing"
                        )
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

            if condition is not None:
                merge_condition(row, condition)
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
        run_as_non_root=spec.get("run_as_non_root") or False,
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
