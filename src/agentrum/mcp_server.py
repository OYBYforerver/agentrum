"""Registry as an MCP server — the IDE integration surface.

Exposes read-only catalog tools over Streamable HTTP at `/mcp` so
Cursor / Claude Code / other MCP clients can discover approved assets
directly. Authentication reuses the HTTP layer: Bearer JWT (account) or
Basic AK/SK (project-scoped, scopes + visibility enforced per tool call).
"""

import base64
import json
import logging

from mcp.server.mcpserver import Context, MCPServer

from agentrum import __version__
from agentrum.db import models
from agentrum.db.engine import SessionLocal

logger = logging.getLogger("agentrum.mcp")

mcp = MCPServer(
    name="agentrum",
    instructions=(
        "Agentrum: the multi-tenant registry for AI agents, MCP servers, "
        "skills and prompts. Use list_resources to discover approved assets "
        "and get_resource for details (including MCP server endpoints)."
    ),
)


def _bearer_from_ctx(ctx: Context) -> str | None:
    headers = getattr(ctx, "headers", None) or {}
    return headers.get("authorization")


async def _resolve_principal(ctx: Context) -> models.User:
    """Resolve the calling principal (JWT or AK/SK) from the HTTP request."""
    from agentrum.auth.deps import _resolve_access_key, _resolve_credential

    auth = _bearer_from_ctx(ctx) or ""
    async with SessionLocal() as session:
        if auth.startswith("Bearer "):
            user = await _resolve_credential(session, auth[7:].strip())
        elif auth.startswith("Basic "):
            try:
                raw = base64.b64decode(auth[6:].strip()).decode()
            except Exception as exc:
                raise PermissionError("malformed Basic credentials") from exc
            username, _, password = raw.partition(":")
            user = await _resolve_access_key(None, session, username, password)
        else:
            user = None
    if user is None:
        raise PermissionError(
            "unauthorized: send 'Authorization: Bearer <jwt>' or Basic AK/SK. "
            "Create credentials in the console (Settings → AK/SK) or via login."
        )
    if user.disabled_at is not None:
        raise PermissionError("account is disabled")
    return user


def _dump(items) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2)


@mcp.tool()
async def registry_overview(ctx: Context) -> str:
    """Agentrum registry overview: counts of visible resources per kind and the server version."""
    from sqlalchemy import func, select

    from agentrum.services import team_service

    user = await _resolve_principal(ctx)
    async with SessionLocal() as session:
        team_ids = await team_service.effective_team_ids(session, user.id)
        from agentrum.services.resource_service import _visibility_clause

        stmt = select(models.Resource.kind, func.count()).group_by(models.Resource.kind)
        vis = _visibility_clause(user, team_ids)
        if vis is not None:
            stmt = stmt.where(vis)
        stmt = stmt.where(models.Resource.deleted_at.is_(None))
        counts = {kind: n for kind, n in (await session.execute(stmt)).all()}
    return _dump({"version": __version__, "resources_by_kind": counts})


@mcp.tool()
async def list_resources(
    ctx: Context,
    kind: str = "",
    namespace: str = "",
    search: str = "",
    limit: int = 20,
) -> str:
    """List visible registry resources.

    Args:
        kind: Agent | MCPServer | Skill | Prompt (empty = all kinds)
        namespace: filter by project namespace
        search: substring match on name/description
        limit: max entries (default 20, max 100)
    """
    from agentrum.services import resource_service

    user = await _resolve_principal(ctx)
    async with SessionLocal() as session:
        items, latest, _total = await resource_service.list_resources(
            session, user,
            kind=kind or None, namespace=namespace or None, q=search or None,
            limit=max(1, min(int(limit), 100)),
        )
        from agentrum.services import team_service

        names = await team_service.usernames(session, [r.created_by for r in items])
    return _dump(
        [
            {
                "ref": f"{r.kind}/{r.namespace}/{r.name}",
                "visibility": r.visibility,
                "description": r.description,
                "latest_tag": (latest[r.id].tag if r.id in latest else None),
                "published_by": names.get(r.created_by),
            }
            for r in items
        ]
    )


@mcp.tool()
async def get_resource(ctx: Context, ref: str, tag: str = "") -> str:
    """Fetch one resource with its latest (or pinned) version spec.

    Args:
        ref: "<kind>/<namespace>/<name>", e.g. "MCPServer/payment/payment-gateway"
        tag: optional immutable tag to pin a specific version
    """
    from agentrum.services import resource_service, team_service

    user = await _resolve_principal(ctx)
    parts = [p for p in ref.split("/") if p]
    if len(parts) != 3:
        raise ValueError(f"ref must be <kind>/<namespace>/<name>, got {ref!r}")
    kind, namespace, name = parts
    async with SessionLocal() as session:
        resource, rv = await resource_service.get_resource(
            session, user, kind, namespace, name, tag=tag or None
        )
        names = await team_service.usernames(session, [resource.created_by])
        from agentrum.services import secret_service

        secret_keys = (
            sorted((await secret_service.get_payloads(session, resource.id)).keys())
            if resource.kind == "Secret"
            else None
        )
    return _dump(
        {
            "kind": resource.kind,
            "namespace": resource.namespace,
            "name": resource.name,
            "visibility": resource.visibility,
            "description": resource.description,
            "catalog": resource.catalog or {},
            "status": resource.status or {},
            "secret_keys": secret_keys,
            "spec": (rv.spec if rv else {}),
            "tag": (rv.tag if rv else None),
            "version": (rv.version if rv else None),
            "change_notes": (rv.change_notes if rv else None),
            "published_by": names.get(resource.created_by),
        }
    )
