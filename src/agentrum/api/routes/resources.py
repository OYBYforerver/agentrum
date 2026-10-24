from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum import audit as audit_mod
from agentrum import errors as err_mod
from agentrum.auth.deps import client_ip, get_current_user
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.schemas.resource import (
    ResourceApplyIn,
    ResourceListOut,
    ResourceOut,
    ResourceVersionOut,
)
from agentrum.services import notification_service, resource_service, secret_service, team_service

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return client_ip(request)


async def _serialize(session: AsyncSession, resources, latest) -> list[ResourceOut]:
    ids = [r.created_by for r in resources]
    if latest:
        ids += [rv.published_by for rv in latest.values()]
    names = await team_service.usernames(session, list(ids))
    out = []
    for r in resources:
        rv = latest.get(r.id)
        secret_keys = None
        if r.kind == "Secret":
            # Key names only — no plaintext ever leaves the database.
            secret_keys = sorted(await secret_service.get_secret_keys(session, r.id))
        out.append(
            ResourceOut(
                kind=r.kind,
                namespace=r.namespace,
                name=r.name,
                visibility=r.visibility,
                labels=r.labels or {},
                description=r.description,
                catalog=r.catalog or {},
                status=r.status or {},
                deprecation=r.deprecation,
                secret_keys=secret_keys,
                created_by=names.get(r.created_by, str(r.created_by)),
                created_at=r.created_at,
                updated_at=r.updated_at,
                deleted_at=r.deleted_at,
                latest_version=(
                    ResourceVersionOut(
                        version=rv.version,
                        tag=rv.tag,
                        spec=rv.spec or {},
                        change_notes=rv.change_notes,
                        published_by=names.get(rv.published_by, str(rv.published_by)),
                        created_at=rv.created_at,
                    )
                    if rv
                    else None
                ),
            )
        )
    return out


@router.put("/{kind}/{namespace}/{name}", response_model=ResourceOut)
async def apply_resource(
    kind: str,
    namespace: str,
    name: str,
    body: ResourceApplyIn,
    request: Request,
    response: Response,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResourceOut:
    resource, rv, created = await resource_service.apply(
        session, user, kind, namespace, name, body, source_ip=_client_ip(request)
    )
    response.status_code = 201 if created else 200
    if rv is None:  # Secret: no versions, values never leave the database
        names = await team_service.usernames(session, [resource.created_by])
        return ResourceOut(
            kind=resource.kind,
            namespace=resource.namespace,
            name=resource.name,
            visibility=resource.visibility,
            labels=resource.labels or {},
            description=resource.description,
            catalog=resource.catalog or {},
            status=resource.status or {},
            deprecation=resource.deprecation,
            secret_keys=sorted(await secret_service.get_secret_keys(session, resource.id)),
            created_by=names.get(resource.created_by, str(resource.created_by)),
            created_at=resource.created_at,
            updated_at=resource.updated_at,
        )
    names = await team_service.usernames(session, [resource.created_by, rv.published_by])
    return ResourceOut(
        kind=resource.kind,
        namespace=resource.namespace,
        name=resource.name,
        visibility=resource.visibility,
        labels=resource.labels or {},
        description=resource.description,
        catalog=resource.catalog or {},
        status=resource.status or {},
        deprecation=resource.deprecation,
        created_by=names.get(resource.created_by, str(resource.created_by)),
        created_at=resource.created_at,
        updated_at=resource.updated_at,
        latest_version=ResourceVersionOut(
            version=rv.version,
            tag=rv.tag,
            spec=rv.spec or {},
            change_notes=rv.change_notes,
            published_by=names.get(rv.published_by, str(rv.published_by)),
            created_at=rv.created_at,
        ),
    )


class ResourcePatchIn(BaseModel):
    description: str | None = None
    labels: dict[str, str] | None = None
    visibility: Literal["internal", "restricted"] | None = None
    catalog: dict[str, Any] | None = None
    # End-of-life: deprecated=True warns subscribers while keeping the
    # resource consumable; deprecated=False clears the marker.
    deprecated: bool | None = None
    deprecation_reason: str | None = None
    successor: str | None = None


@router.patch("/{kind}/{namespace}/{name}", response_model=ResourceOut)
async def patch_resource(
    kind: str,
    namespace: str,
    name: str,
    body: ResourcePatchIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResourceOut:
    """Edit mutable metadata (description/labels/visibility/catalog) WITHOUT
    creating a version — spec and tags stay immutable."""

    from agentrum.schemas.specs import validate_catalog

    kind_n = resource_service.normalize_kind(kind)
    resource = await resource_service._get_resource(session, kind_n, namespace, name)
    if resource is None:
        raise err_mod.NotFoundError(f"{kind}/{namespace}/{name} not found")
    # Same bar as publishing this kind: patching a Deployment needs deploy
    # rights, everything else developer-or-higher.
    await resource_service._require_publish_role(session, user, namespace, kind=kind_n)
    if body.visibility is not None:
        # Visibility invariants live here for every kind: Prompts are always
        # project-private, Secrets are always restricted.
        if kind_n == "Prompt":
            resource.visibility = models.VISIBILITY_PRIVATE
        elif kind_n == "Secret":
            raise err_mod.ValidationError("Secrets are always restricted")
        else:
            resource.visibility = body.visibility
    if body.description is not None:
        resource.description = body.description
    if body.labels is not None:
        resource.labels = body.labels
    if body.catalog is not None:
        resource.catalog = validate_catalog(body.catalog)
    if body.deprecated is not None:
        if body.deprecated:
            resource.deprecation = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "by": user.username,
                "reason": body.deprecation_reason,
                "successor": body.successor,
            }
        else:
            resource.deprecation = None
    await audit_mod.record(
        session, actor=user, action="resource.update", kind=kind_n,
        namespace=namespace, name=name,
        detail=(
            {"deprecated": body.deprecated, "successor": body.successor}
            if body.deprecated is not None
            else {}
        ),
        source_ip=client_ip(request),
    )
    await session.commit()
    if body.deprecated is True:
        # Subscribers learn about the deprecation right after the marker is
        # durable (impact warning — see notification_service).
        await notification_service.enqueue_resource_deprecated(
            session, resource, user.username, body.deprecation_reason, body.successor
        )
        await session.commit()
    await session.refresh(resource)
    items = await _serialize(session, [resource], {})
    return items[0]


@router.get("", response_model=ResourceListOut)
async def list_resources(
    kind: str | None = None,
    namespace: str | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResourceListOut:
    # Tombstones are a housekeeping view for platform admins, not a
    # catalog feature for everyone.
    if include_deleted and not user.is_platform_admin:
        raise err_mod.PermissionDeniedError("only platform admins can list deleted resources")
    resources, latest, total = await resource_service.list_resources(
        session, user, kind=kind, namespace=namespace, q=q,
        include_deleted=include_deleted, limit=limit, offset=offset,
    )
    return ResourceListOut(
        items=await _serialize(session, resources, latest), total=total, limit=limit, offset=offset
    )


@router.get("/{kind}/{namespace}/{name}", response_model=ResourceOut)
async def get_resource(
    kind: str,
    namespace: str,
    name: str,
    tag: str | None = None,
    version: int | None = None,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResourceOut:
    resource, rv = await resource_service.get_resource(
        session, user, kind, namespace, name, tag=tag, version=version
    )
    items = await _serialize(
        session, [resource], {resource.id: rv} if rv is not None else {}
    )
    return items[0]


@router.get("/{kind}/{namespace}/{name}/connect")
async def get_connection(
    kind: str,
    namespace: str,
    name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ready-to-paste client configuration for a published MCP server
    (Claude Code / Cursor / generic). Requires normal read access."""
    from agentrum.services import connect_service

    kind_n = resource_service.normalize_kind(kind)
    if kind_n != "MCPServer":
        raise err_mod.ValidationError("connection snippets are only available for MCPServer")
    resource, rv = await resource_service.get_resource(
        session, user, kind, namespace, name
    )
    return connect_service.build(resource, rv.spec if rv else {})


@router.get("/{kind}/{namespace}/{name}/versions", response_model=list[ResourceVersionOut])
async def list_versions(
    kind: str,
    namespace: str,
    name: str,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ResourceVersionOut]:
    _resource, versions = await resource_service.list_versions(
        session, user, kind, namespace, name
    )
    names = await team_service.usernames(session, [v.published_by for v in versions])
    return [
        ResourceVersionOut(
            version=v.version,
            tag=v.tag,
            spec=v.spec or {},
            published_by=names.get(v.published_by, str(v.published_by)),
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.delete("/{kind}/{namespace}/{name}", status_code=204)
async def delete_resource(
    kind: str,
    namespace: str,
    name: str,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await resource_service.delete_resource(
        session, user, kind, namespace, name, source_ip=_client_ip(request)
    )
