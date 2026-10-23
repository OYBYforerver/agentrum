"""Resource publish/read logic with visibility and subscription-aware access."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit, errors
from agentrum.auth.ak_context import ak_project_id, has_scope
from agentrum.db import models
from agentrum.schemas.specs import validate_catalog, validate_spec
from agentrum.services import git_service, notification_service, secret_service, team_service

NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")

KIND_ALIASES = {
    "agent": "Agent",
    "mcpserver": "MCPServer",
    "mcp_server": "MCPServer",
    "server": "MCPServer",
    "skill": "Skill",
    "prompt": "Prompt",
}


def normalize_kind(raw: str) -> str:
    kind = KIND_ALIASES.get((raw or "").lower(), raw)
    if kind not in models.KINDS:
        raise errors.ValidationError(f"unknown kind {raw!r}; expected one of {list(models.KINDS)}")
    return kind


async def _require_publish_role(
    session: AsyncSession, actor: models.User, namespace_name: str
) -> models.Namespace:
    ns = await session.get(models.Namespace, namespace_name)
    if ns is None:
        raise errors.NotFoundError(f"namespace {namespace_name!r} not found")
    if ak_project_id() is not None:
        if ak_project_id() != str(ns.team_id):
            raise errors.PermissionDeniedError(
                f"access key is scoped to a different project, not {namespace_name!r}"
            )
        if not has_scope("publish"):
            raise errors.PermissionDeniedError("access key lacks the 'publish' scope")
        return ns
    if actor.is_platform_admin:
        return ns
    role = await team_service.get_team_role(session, actor.id, ns.team_id)
    if role not in (models.ROLE_ADMIN, models.ROLE_PUBLISHER):
        raise errors.PermissionDeniedError(
            f"publisher role required in namespace {namespace_name!r}"
        )
    return ns


async def _get_resource(
    session: AsyncSession, kind: str, namespace: str, name: str, include_deleted: bool = False
) -> models.Resource | None:
    stmt = select(models.Resource).where(
        models.Resource.kind == kind,
        models.Resource.namespace == namespace,
        models.Resource.name == name,
    )
    if not include_deleted:
        stmt = stmt.where(models.Resource.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def _subscription_grants_read(
    session: AsyncSession, team_ids: list[uuid.UUID], resource: models.Resource
) -> bool:
    if not team_ids:
        return False
    stmt = (
        select(models.Subscription.id)
        .where(
            models.Subscription.subscriber_team_id.in_(team_ids),
            models.Subscription.status == models.SUB_ACTIVE,
            models.Subscription.kind == resource.kind,
            models.Subscription.namespace == resource.namespace,
            models.Subscription.name.in_([resource.name, "*"]),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _assert_can_read(session: AsyncSession, actor: models.User, resource: models.Resource) -> None:
    if actor.is_platform_admin or resource.visibility == models.VISIBILITY_INTERNAL:
        return
    team_ids = await team_service.effective_team_ids(session, actor.id)
    ns = await session.get(models.Namespace, resource.namespace)
    if ns is not None and ns.team_id in team_ids:
        return
    if resource.visibility == models.VISIBILITY_PRIVATE:
        # Project-private (Prompts): not even subscriptions grant access.
        raise errors.PermissionDeniedError(
            f"{resource.namespace}/{resource.name} is private to its project"
        )
    if await _subscription_grants_read(session, team_ids, resource):
        return
    raise errors.PermissionDeniedError(
        f"{resource.namespace}/{resource.name} is restricted; ask to subscribe first"
    )


def _visibility_clause(actor: models.User, team_ids: list[uuid.UUID]):
    """SQL clause limiting list results to what the actor may see."""
    if actor.is_platform_admin:
        return None
    owned = select(models.Namespace.name).where(models.Namespace.team_id.in_(team_ids))
    subscribed = exists(
        select(models.Subscription.id).where(
            models.Subscription.subscriber_team_id.in_(team_ids),
            models.Subscription.status == models.SUB_ACTIVE,
            models.Subscription.kind == models.Resource.kind,
            models.Subscription.namespace == models.Resource.namespace,
            models.Subscription.name.in_([models.Resource.name, "*"]),
        )
    )
    return or_(
        models.Resource.visibility == models.VISIBILITY_INTERNAL,
        models.Resource.namespace.in_(owned),
        subscribed,
    )


async def apply(
    session: AsyncSession, actor: models.User, kind_raw: str, namespace: str, name: str,
    data, source_ip: str | None = None,
) -> tuple[models.Resource, models.ResourceVersion, bool]:
    """Create or update a resource, appending an immutable version."""
    kind = normalize_kind(kind_raw)
    if kind == "Secret":
        return await _apply_secret(session, actor, namespace, name, data, source_ip=source_ip)
    if not NAME_RE.match(name or ""):
        raise errors.ValidationError("resource name must be lowercase alphanumeric/'-', 2-253 chars")
    if data.tag is not None and not TAG_RE.match(data.tag):
        raise errors.ValidationError("tag must be 1-63 chars of letters, digits, '.', '_' or '-'")
    # Authorization first: unauthorized callers never see schema details.
    await _require_publish_role(session, actor, namespace)
    spec = validate_spec(kind, data.spec)

    # Prompts are project-private: visibility is forced, cross-project sharing
    # (subscriptions) is rejected at the subscription layer.
    if kind == "Prompt":
        data.visibility = models.VISIBILITY_PRIVATE

    # Git-backed skills: resolve the ref to a commit SHA at publish time so
    # the immutable version pins exact upstream content. Failure blocks publish.
    if kind == "Skill" and (spec.get("source") or {}).get("git"):
        spec["source"]["git"] = await git_service.resolve_git_source(
            session, namespace, spec["source"]["git"]
        )

    if kind == "Deployment":
        target = await _get_resource(
            session, spec["target_kind"], spec["target_namespace"], spec["target_name"]
        )
        if target is None:
            raise errors.ValidationError(
                f"deployment target {spec['target_kind']}/{spec['target_namespace']}/"
                f"{spec['target_name']} not found"
            )

    now = datetime.now(UTC)
    resource = await _get_resource(session, kind, namespace, name, include_deleted=True)
    created = resource is None

    try:
        catalog = validate_catalog(data.catalog)
        if created:
            resource = models.Resource(
                kind=kind,
                namespace=namespace,
                name=name,
                visibility=data.visibility or models.VISIBILITY_INTERNAL,
                labels=data.labels or {},
                description=data.description,
                catalog=catalog,
                created_by=actor.id,
            )
            session.add(resource)
            await session.flush()
        else:
            resource.deleted_at = None  # re-applying a deleted resource restores it
            if data.labels is not None:
                resource.labels = data.labels
            if data.description is not None:
                resource.description = data.description
            if data.visibility is not None:
                resource.visibility = data.visibility
            if data.catalog is not None:
                resource.catalog = catalog

        if data.tag is not None:
            dup = (
                await session.execute(
                    select(models.ResourceVersion.id).where(
                        models.ResourceVersion.resource_id == resource.id,
                        models.ResourceVersion.tag == data.tag,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise errors.ConflictError(f"tag {data.tag!r} already exists; tags are immutable")

        max_version = (
            await session.execute(
                select(func.max(models.ResourceVersion.version)).where(
                    models.ResourceVersion.resource_id == resource.id
                )
            )
        ).scalar() or 0

        rv = models.ResourceVersion(
            resource_id=resource.id,
            version=max_version + 1,
            tag=data.tag,
            spec=spec,
            change_notes=data.change_notes,
            published_by=actor.id,
        )
        session.add(rv)
        resource.updated_at = now

        await audit.record(
            session, actor=actor, action="resource.publish", kind=kind, namespace=namespace,
            name=name, detail={"version": rv.version, "tag": data.tag}, source_ip=source_ip,
        )
        # Transactional outbox: subscribers learn about the new version in the
        # same commit that creates it.
        await notification_service.enqueue_resource_published(
            session, resource, rv, publisher_name=actor.username
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise errors.ConflictError("concurrent modification, please retry") from exc

    await session.refresh(resource)
    if rv is not None:
        await session.refresh(rv)
    return resource, rv, created


async def _apply_secret(
    session: AsyncSession, actor: models.User, namespace: str, name: str, data,
    source_ip: str | None = None,
) -> tuple[models.Resource, None, bool]:
    """Secret resources: encrypted key/value payload, no versions, values
    never leave the database unencrypted."""
    payload = (data.spec or {}).get("data")
    if not isinstance(payload, dict) or not payload:
        raise errors.ValidationError("Secret spec must be {\"data\": {<key>: <value>}}")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in payload.items()):
        raise errors.ValidationError("Secret data keys and values must be strings")
    if not NAME_RE.match(name or ""):
        raise errors.ValidationError("resource name must be lowercase alphanumeric/'-', 2-253 chars")
    await _require_publish_role(session, actor, namespace)

    resource = await _get_resource(session, "Secret", namespace, name, include_deleted=True)
    created = resource is None
    if created:
        resource = models.Resource(
            kind="Secret",
            namespace=namespace,
            name=name,
            visibility=data.visibility or models.VISIBILITY_RESTRICTED,
            labels=data.labels or {},
            description=data.description,
            created_by=actor.id,
        )
        session.add(resource)
        await session.flush()
    else:
        resource.deleted_at = None
        if data.visibility is not None:
            resource.visibility = data.visibility
        if data.description is not None:
            resource.description = data.description

    await secret_service.set_payloads(session, resource.id, payload)
    await audit.record(
        session, actor=actor, action="secret.set", kind="Secret", namespace=namespace,
        name=name, detail={"keys": sorted(payload)}, source_ip=source_ip,
    )
    await session.commit()
    await session.refresh(resource)
    return resource, None, created


async def list_resources(
    session: AsyncSession, actor: models.User, kind: str | None = None,
    namespace: str | None = None, q: str | None = None, include_deleted: bool = False,
    limit: int = 50, offset: int = 0,
) -> tuple[list[models.Resource], dict[uuid.UUID, models.ResourceVersion], int]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = select(models.Resource)
    vis = _visibility_clause(
        actor, await team_service.effective_team_ids(session, actor.id)
    )
    if vis is not None:
        stmt = stmt.where(vis)
    if kind:
        stmt = stmt.where(models.Resource.kind == normalize_kind(kind))
    if namespace:
        stmt = stmt.where(models.Resource.namespace == namespace)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(models.Resource.name.ilike(pattern), models.Resource.description.ilike(pattern))
        )
    if not include_deleted:
        stmt = stmt.where(models.Resource.deleted_at.is_(None))

    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    resources = (
        await session.execute(
            stmt.order_by(models.Resource.updated_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    latest: dict[uuid.UUID, models.ResourceVersion] = {}
    if resources:
        ids = [r.id for r in resources]
        rows = (
            await session.execute(
                select(models.ResourceVersion)
                .where(models.ResourceVersion.resource_id.in_(ids))
                .order_by(models.ResourceVersion.version.desc())
            )
        ).scalars().all()
        for rv in rows:
            latest.setdefault(rv.resource_id, rv)
    return list(resources), latest, total


async def get_resource(
    session: AsyncSession, actor: models.User, kind_raw: str, namespace: str, name: str,
    tag: str | None = None, version: int | None = None,
) -> tuple[models.Resource, models.ResourceVersion | None]:
    kind = normalize_kind(kind_raw)
    resource = await _get_resource(session, kind, namespace, name)
    if resource is None:
        raise errors.NotFoundError(f"{kind.lower()}/{namespace}/{name} not found")
    await _assert_can_read(session, actor, resource)

    stmt = select(models.ResourceVersion).where(models.ResourceVersion.resource_id == resource.id)
    if tag is not None:
        stmt = stmt.where(models.ResourceVersion.tag == tag)
    elif version is not None:
        stmt = stmt.where(models.ResourceVersion.version == version)
    else:
        stmt = stmt.order_by(models.ResourceVersion.version.desc()).limit(1)
    rv = (await session.execute(stmt)).scalars().first()
    return resource, rv


async def list_versions(
    session: AsyncSession, actor: models.User, kind_raw: str, namespace: str, name: str
) -> tuple[models.Resource, list[models.ResourceVersion]]:
    kind = normalize_kind(kind_raw)
    resource = await _get_resource(session, kind, namespace, name)
    if resource is None:
        raise errors.NotFoundError(f"{kind.lower()}/{namespace}/{name} not found")
    await _assert_can_read(session, actor, resource)
    rows = (
        await session.execute(
            select(models.ResourceVersion)
            .where(models.ResourceVersion.resource_id == resource.id)
            .order_by(models.ResourceVersion.version.desc())
        )
    ).scalars().all()
    return resource, list(rows)


async def delete_resource(
    session: AsyncSession, actor: models.User, kind_raw: str, namespace: str, name: str,
    source_ip: str | None = None,
) -> None:
    kind = normalize_kind(kind_raw)
    resource = await _get_resource(session, kind, namespace, name)
    if resource is None:
        raise errors.NotFoundError(f"{kind.lower()}/{namespace}/{name} not found")
    await _require_publish_role(session, actor, namespace)
    resource.deleted_at = datetime.now(UTC)
    await audit.record(
        session, actor=actor, action="resource.delete", kind=kind, namespace=namespace, name=name,
        source_ip=source_ip,
    )
    # Cascade: active subscribers are told about the deletion (impact awareness).
    await notification_service.enqueue_resource_deleted(
        session, resource, actor_name=actor.username
    )
    await session.commit()
