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
        "and get_resource for details — MCP server entries carry a `connect` "
        "block with ready-to-paste client configuration."
    ),
)


def _bearer_from_ctx(ctx: Context) -> str | None:
    headers = getattr(ctx, "headers", None) or {}
    if hasattr(headers, "get"):
        value = headers.get("authorization")
        if value is not None:
            return value
    # Header maps outside the real transport (tests, middleware shims) may
    # keep the original casing.
    for key, value in headers.items():
        if str(key).lower() == "authorization":
            return value
    return None


async def _resolve_principal(ctx: Context) -> models.User:
    """Resolve the calling principal (JWT or AK/SK) from the HTTP request."""
    from fastapi import HTTPException

    from agentrum.auth.ak_context import ak_project_id_var, ak_scopes_var
    from agentrum.auth.deps import _resolve_access_key, _resolve_credential

    # Same defensive reset as the REST path: reused tasks must not inherit a
    # previous call's AK project/scopes.
    ak_project_id_var.set(None)
    ak_scopes_var.set(())

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
            try:
                # IP-based rate limiting is meaningless for server-side MCP
                # calls (one shared source address); the per-AK lockout stays.
                user = await _resolve_access_key(
                    None, session, username, password, enforce_ip_limit=False
                )
            except HTTPException as exc:
                raise PermissionError(str(exc.detail)) from exc
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
                "deprecated": r.deprecation is not None,
                "latest_tag": (latest[r.id].tag if r.id in latest else None),
                "published_by": names.get(r.created_by),
            }
            for r in items
        ]
    )


@mcp.tool()
async def list_prompts(ctx: Context, search: str = "", limit: int = 50) -> str:
    """List prompt templates visible to you.

    Prompts are project-private: you see your project's templates only.
    Each entry carries its declared variables so clients can build forms.

    Args:
        search: substring match on name/description
        limit: max entries (default 50, max 100)
    """
    from agentrum.services import resource_service

    user = await _resolve_principal(ctx)
    async with SessionLocal() as session:
        items, latest, _total = await resource_service.list_resources(
            session, user, kind="Prompt", q=search or None,
            limit=max(1, min(int(limit), 100)),
        )
        return _dump(
            [
                {
                    "ref": f"{r.kind}/{r.namespace}/{r.name}",
                    "description": r.description,
                    "latest_tag": (latest[r.id].tag if r.id in latest else None),
                    "variables": (
                        (latest[r.id].spec or {}).get("variables", [])
                        if r.id in latest
                        else []
                    ),
                }
                for r in items
            ]
        )


@mcp.tool()
async def get_prompt(
    ctx: Context, ref: str, tag: str = "", variables_json: str = ""
) -> str:
    """Fetch a prompt template, or render it with concrete values.

    Without variables_json: the template and its declared variables.
    With variables_json (a JSON object): the rendered prompt text,
    validated against the declaration (required/unknown variables error).

    Args:
        ref: "Prompt/<namespace>/<name>"
        tag: optional immutable tag (default: latest)
        variables_json: JSON object of variable values, e.g. {"language": "python"}
    """
    import json as _json

    from agentrum.services import prompt_service, resource_service

    user = await _resolve_principal(ctx)
    parts = [p for p in ref.split("/") if p]
    if len(parts) != 3 or parts[0].lower() != "prompt":
        raise ValueError(f"ref must be Prompt/<namespace>/<name>, got {ref!r}")
    _, namespace, name = parts
    async with SessionLocal() as session:
        resource, rv = await resource_service.get_resource(
            session, user, "Prompt", namespace, name, tag=tag or None
        )
        if rv is None:
            raise ValueError("prompt has no published version")
        spec = rv.spec or {}
        if not variables_json:
            return _dump(
                {
                    "ref": f"Prompt/{resource.namespace}/{resource.name}",
                    "tag": rv.tag,
                    "template": spec.get("template"),
                    "variables": spec.get("variables", []),
                }
            )
        try:
            variables = _json.loads(variables_json)
        except ValueError:
            raise ValueError("variables_json must be a JSON object") from None
        if not isinstance(variables, dict):
            # decoded JSON with the wrong shape is a bad value, not a type error
            raise ValueError("variables_json must be a JSON object")  # noqa: TRY004
        return prompt_service.render(spec, variables)


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
            sorted(await secret_service.get_secret_keys(session, resource.id))
            if resource.kind == "Secret"
            else None
        )
        connect = None
        if resource.kind == "MCPServer" and rv is not None:
            from agentrum.services import connect_service

            connect = connect_service.build(resource, rv.spec or {})
    return _dump(
        {
            "kind": resource.kind,
            "namespace": resource.namespace,
            "name": resource.name,
            "visibility": resource.visibility,
            "description": resource.description,
            "catalog": resource.catalog or {},
            "status": resource.status or {},
            "deprecation": resource.deprecation,
            "secret_keys": secret_keys,
            "connect": connect,
            "spec": (rv.spec if rv else {}),
            "tag": (rv.tag if rv else None),
            "version": (rv.version if rv else None),
            "change_notes": (rv.change_notes if rv else None),
            "published_by": names.get(resource.created_by),
        }
    )
