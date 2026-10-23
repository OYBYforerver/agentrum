from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from agentrum.auth.deps import get_current_user
from agentrum.db import models
from agentrum.db.engine import get_session
from agentrum.schemas.resource import (
    ResourceApplyIn,
    ResourceListOut,
    ResourceOut,
    ResourceVersionOut,
)
from agentrum.services import resource_service, team_service

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _serialize(session: AsyncSession, resources, latest) -> list[ResourceOut]:
    ids = [r.created_by for r in resources]
    if latest:
        ids += [rv.published_by for rv in latest.values()]
    names = await team_service.usernames(session, list(ids))
    out = []
    for r in resources:
        rv = latest.get(r.id)
        out.append(
            ResourceOut(
                kind=r.kind,
                namespace=r.namespace,
                name=r.name,
                visibility=r.visibility,
                labels=r.labels or {},
                description=r.description,
                created_by=names.get(r.created_by, str(r.created_by)),
                created_at=r.created_at,
                updated_at=r.updated_at,
                deleted_at=r.deleted_at,
                latest_version=(
                    ResourceVersionOut(
                        version=rv.version,
                        tag=rv.tag,
                        spec=rv.spec or {},
                        published_by=names.get(rv.published_by, str(rv.published_by)),
                        created_at=rv.created_at,
                    )
                    if rv
                    else None
                ),
            )
        )
    return out


@router.put("/{kind}/{namespace}/{name}", response_model=ResourceOut, status_code=201)
async def apply_resource(
    kind: str,
    namespace: str,
    name: str,
    body: ResourceApplyIn,
    request: Request,
    user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResourceOut:
    resource, rv, _created = await resource_service.apply(
        session, user, kind, namespace, name, body, source_ip=_client_ip(request)
    )
    names = await team_service.usernames(session, [resource.created_by, rv.published_by])
    return ResourceOut(
        kind=resource.kind,
        namespace=resource.namespace,
        name=resource.name,
        visibility=resource.visibility,
        labels=resource.labels or {},
        description=resource.description,
        created_by=names.get(resource.created_by, str(resource.created_by)),
        created_at=resource.created_at,
        updated_at=resource.updated_at,
        latest_version=ResourceVersionOut(
            version=rv.version,
            tag=rv.tag,
            spec=rv.spec or {},
            published_by=names.get(rv.published_by, str(rv.published_by)),
            created_at=rv.created_at,
        ),
    )


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
