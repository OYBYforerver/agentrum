"""Agentrum CLI — login, apply, get, delete against a registry server."""

import json
import os
from pathlib import Path

import httpx
import typer
import yaml

app = typer.Typer(
    help="Agentrum — multi-tenant registry for AI agents, MCP servers, skills and prompts.",
    no_args_is_help=True,
)

_CREDENTIALS = Path.home() / ".agentrum" / "credentials.json"


def _load_credentials() -> dict:
    if _CREDENTIALS.exists():
        return json.loads(_CREDENTIALS.read_text())
    return {}


def _save_credentials(data: dict) -> None:
    """Atomically create the credentials file with 0600 — no world-readable
    window between write and chmod."""
    _CREDENTIALS.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = _CREDENTIALS.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(data))
    os.replace(tmp, _CREDENTIALS)


def _detail(resp: httpx.Response) -> str:
    """Best-effort error detail: proxies and error pages are not JSON."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        return str(body.get("detail") or body)
    return str(body)


def _server() -> str:
    server = os.environ.get("AGENTRUM_SERVER") or _load_credentials().get("server")
    if not server:
        typer.echo("Not logged in. Run: agentrum login --server <url> ...", err=True)
        raise typer.Exit(1)
    return server.rstrip("/")


def _headers() -> dict:
    ak = os.environ.get("AGENTRUM_AK") or _load_credentials().get("ak")
    sk = os.environ.get("AGENTRUM_SK") or _load_credentials().get("sk")
    if ak and sk:
        import base64

        raw = base64.b64encode(f"{ak}:{sk}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}
    token = os.environ.get("AGENTRUM_TOKEN") or _load_credentials().get("token")
    if not token:
        typer.echo("Not logged in. Run: agentrum login ...", err=True)
        raise typer.Exit(1)
    return {"Authorization": f"Bearer {token}"}


@app.command()
def login(
    server: str = typer.Option(..., help="Registry base URL, e.g. http://localhost:12122"),
    username: str = typer.Option(None, prompt=True),
    password: str = typer.Option("", prompt=True, hide_input=True),
    ak: str = typer.Option(None, help="Project access key (AK/SK login for CI)"),
    sk: str = typer.Option(None, help="Project secret key (used with --ak, hidden input)"),
) -> None:
    """Authenticate and store credentials locally (chmod 0600).

    Either username/password (console session) or --ak/--sk (project-scoped
    machine credential; scopes apply)."""
    if ak and not sk:
        sk = typer.prompt("SK", hide_input=True)
    if ak and sk:
        _save_credentials({"server": server.rstrip("/"), "ak": ak, "sk": sk})
        typer.echo(f"✔ stored AK/SK for {server} (project-scoped)")
        return
    try:
        resp = httpx.post(
            f"{server.rstrip('/')}/v1/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        typer.echo(f"cannot reach {server}: {exc}", err=True)
        raise typer.Exit(1) from None
    if resp.status_code != 200:
        typer.echo(f"login failed ({resp.status_code}): {_detail(resp)}", err=True)
        raise typer.Exit(1)
    _save_credentials({"server": server.rstrip("/"), "token": resp.json()["access_token"]})
    typer.echo(f"✔ logged in to {server} as {username}")


@app.command()
def apply(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Apply YAML manifests (documents separated by ---), kubectl-style."""
    docs = [d for d in yaml.safe_load_all(file.read_text()) if d]
    if not docs:
        typer.echo("no documents found in manifest", err=True)
        raise typer.Exit(1)
    with httpx.Client(base_url=_server(), headers=_headers(), timeout=30) as client:
        failed = 0
        for doc in docs:
            if not isinstance(doc, dict):
                typer.echo("✘ manifest contains a non-object document", err=True)
                failed += 1
                continue
            kind = doc.get("kind", "")
            meta = doc.get("metadata") or {}
            name = meta.get("name", "")
            namespace = meta.get("namespace", "default")
            body: dict = {"spec": doc.get("spec") or {}}
            for key in ("tag", "labels", "description", "visibility"):
                value = doc.get(key, meta.get(key))
                if value is not None:
                    body[key] = value
            resp = client.put(f"/v1/resources/{kind}/{namespace}/{name}", json=body)
            mark = "✔" if resp.status_code in (200, 201) else "✘"
            typer.echo(f"{mark} {kind}/{namespace}/{name} -> {resp.status_code}")
            if resp.status_code not in (200, 201):
                failed += 1
                typer.echo(f"    {_detail(resp)}", err=True)
        if failed:
            raise typer.Exit(1)


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(h), *(len(str(r[i])) for r in rows)) if rows else len(h)
        for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    typer.echo(fmt.format(*headers))
    typer.echo(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        typer.echo(fmt.format(*[str(c) for c in row]))


@app.command(name="get")
def get_cmd(
    kind: str,
    name: str | None = typer.Argument(None),
    namespace: str | None = typer.Option(None, "-n", "--namespace"),
    all_namespaces: bool = typer.Option(False, "-A", "--all-namespaces"),
) -> None:
    """List resources of a kind, or show one resource."""
    with httpx.Client(base_url=_server(), headers=_headers(), timeout=30) as client:
        if name:
            if not namespace:
                typer.echo("namespace is required when NAME is given (-n)", err=True)
                raise typer.Exit(1)
            resp = client.get(f"/v1/resources/{kind}/{namespace}/{name}")
            if resp.status_code != 200:
                typer.echo(_detail(resp), err=True)
                raise typer.Exit(1)
            typer.echo(json.dumps(resp.json(), indent=2, ensure_ascii=False))
            return
        params: dict = {"kind": kind, "limit": 200}
        if namespace and not all_namespaces:
            params["namespace"] = namespace
        resp = client.get("/v1/resources", params=params)
        if resp.status_code != 200:
            typer.echo(_detail(resp), err=True)
            raise typer.Exit(1)
        items = resp.json()["items"]
        rows = [
            [
                it["kind"],
                it["namespace"],
                it["name"],
                it["visibility"],
                (it.get("latest_version") or {}).get("tag") or f"v{(it.get('latest_version') or {}).get('version', '-')}",
                it["updated_at"][:19],
            ]
            for it in items
        ]
        _print_table(["KIND", "NAMESPACE", "NAME", "VISIBILITY", "TAG", "UPDATED"], rows)
        typer.echo(f"\n{len(items)} resource(s)")


@app.command()
def delete(
    kind: str,
    ref: str = typer.Argument(..., help="namespace/name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the confirmation prompt"),
) -> None:
    """Soft-delete a resource (re-apply restores it)."""
    namespace, _, name = ref.partition("/")
    if not namespace or not name:
        typer.echo("ref must be namespace/name", err=True)
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"Delete {kind}/{namespace}/{name}?"):
        raise typer.Exit(1)
    with httpx.Client(base_url=_server(), headers=_headers(), timeout=30) as client:
        resp = client.delete(f"/v1/resources/{kind}/{namespace}/{name}")
        if resp.status_code == 204:
            typer.echo(f"✔ deleted {kind}/{namespace}/{name}")
        else:
            typer.echo(_detail(resp), err=True)
            raise typer.Exit(1)


@app.command()
def configure(
    client: str = typer.Option(
        ..., "--client", help="cursor | claude-code | generic (generic prints the snippet)"
    ),
    server: str = typer.Option(None, help="Registry base URL (default: stored/login server)"),
    name: str = typer.Option("agentrum", help="Entry name in the client config"),
    output: str = typer.Option(None, help="Config file path (client default if omitted)"),
) -> None:
    """Write this registry into an MCP client config (read-only access).

    Prefers stored AK/SK credentials; a stored console token works too but
    expires (use `agentrum login --ak … --sk …` for a long-lived setup).
    Existing entries in the file are preserved; only `name` is (over)written.
    """
    import base64

    creds = _load_credentials()
    base = (server or os.environ.get("AGENTRUM_SERVER") or creds.get("server") or "").rstrip("/")
    if not base:
        typer.echo(
            "No server known. Pass --server or run: agentrum login --server <url> ...", err=True
        )
        raise typer.Exit(1)
    ak = os.environ.get("AGENTRUM_AK") or creds.get("ak")
    sk = os.environ.get("AGENTRUM_SK") or creds.get("sk")
    token = os.environ.get("AGENTRUM_TOKEN") or creds.get("token")
    if ak and sk:
        auth = "Basic " + base64.b64encode(f"{ak}:{sk}".encode()).decode()
    elif token:
        auth = f"Bearer {token}"
        typer.echo(
            "note: using a console session token (expires in hours). For a long-lived "
            "setup, log in with a project AK/SK: agentrum login --ak … --sk …"
        )
    else:
        typer.echo("Not logged in. Run: agentrum login ...", err=True)
        raise typer.Exit(1)

    client_n = client.strip().lower()
    if client_n == "cursor":
        entry: dict = {"url": f"{base}/mcp", "headers": {"Authorization": auth}}
        path = Path(output) if output else Path.home() / ".cursor" / "mcp.json"
    elif client_n == "claude-code":
        entry = {"type": "http", "url": f"{base}/mcp", "headers": {"Authorization": auth}}
        path = Path(output) if output else Path.cwd() / ".mcp.json"
    elif client_n == "generic":
        typer.echo(
            json.dumps(
                {"mcpServers": {name: {"url": f"{base}/mcp", "headers": {"Authorization": auth}}}},
                indent=2,
            )
        )
        return
    else:
        typer.echo("unknown --client (use cursor | claude-code | generic)", err=True)
        raise typer.Exit(1)

    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            typer.echo(f"{path} is not valid JSON — not touching it, merge manually", err=True)
            raise typer.Exit(1)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    action = "updated" if name in servers else "added"
    servers[name] = entry
    data["mcpServers"] = servers

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(data, indent=2))
    os.replace(tmp, path)
    # The file carries credentials — tighten unconditionally: a pre-existing
    # config (Cursor's, or a repo-tracked .mcp.json) may well be world-readable.
    os.chmod(path, 0o600)
    typer.echo(f"✔ {action} '{name}' in {path} ({base}/mcp)")


@app.command()
def version() -> None:
    """Show server version."""
    resp = httpx.get(f"{_server()}/health", timeout=10)
    typer.echo(json.dumps(resp.json(), ensure_ascii=False))


_INIT_TEMPLATES: dict[str, dict] = {
    "agent": {
        "$schema": "http://localhost:12122/v1/schema/manifest.json",
        "kind": "Agent",
        "metadata": {"name": "my-agent", "namespace": "default", "labels": {}},
        "spec": {
            "image": "registry.internal/my-agent:0.1.0",
            "framework": "langgraph",
            "protocol": "mcp",
            "capabilities": [],
        },
        "description": "TODO: what does this agent do",
        "tag": "v0.1.0",
    },
    "mcp-server": {
        "$schema": "http://localhost:12122/v1/schema/manifest.json",
        "kind": "MCPServer",
        "metadata": {"name": "my-server", "namespace": "default", "labels": {}},
        "spec": {
            "transport": "streamable-http",
            "endpoint": "http://localhost:3000/mcp",
            # remote auth example:
            # {"name": "Authorization", "value_from": {"secret_ref": {"name": "creds", "key": "token"}}}
            "headers": [],
        },
        "description": "TODO: tools exposed by this MCP server",
        "tag": "v0.1.0",
    },
    "skill": {
        "$schema": "http://localhost:12122/v1/schema/manifest.json",
        "kind": "Skill",
        "metadata": {"name": "my-skill", "namespace": "default", "labels": {}},
        "spec": {
            "entrypoint": "SKILL.md",
            "instructions": "TODO: how to use this skill",
        },
        "description": "TODO: skill summary",
        "tag": "v0.1.0",
    },
    "prompt": {
        "$schema": "http://localhost:12122/v1/schema/manifest.json",
        "kind": "Prompt",
        "metadata": {"name": "my-prompt", "namespace": "default", "labels": {}},
        "spec": {
            "template": "TODO: prompt template with {{variables}}",
            "variables": [{"name": "variables", "description": "TODO"}],
        },
        "description": "TODO: prompt purpose",
        "tag": "v0.1.0",
    },
}


@app.command()
def init(
    kind: str = typer.Argument(..., help="agent | mcp-server | skill | prompt"),
    name: str = typer.Argument(..., help="project/resource name"),
) -> None:
    """Scaffold a new asset project (agentrum.yaml + README stub)."""
    if kind not in _INIT_TEMPLATES:
        typer.echo(f"kind must be one of: {', '.join(_INIT_TEMPLATES)}", err=True)
        raise typer.Exit(1)
    target = Path(name)
    if target.exists():
        typer.echo(f"directory {name} already exists", err=True)
        raise typer.Exit(1)
    target.mkdir(parents=True)
    template = json.loads(json.dumps(_INIT_TEMPLATES[kind]))  # deep copy
    template["metadata"]["name"] = name
    (target / "agentrum.yaml").write_text(yaml.safe_dump(template, sort_keys=False, allow_unicode=True))
    (target / "README.md").write_text(
        f"# {name}\n\nTODO: long description (markdown). Publish with:\n\n"
        f"    agentrum apply {name}/agentrum.yaml\n"
    )
    typer.echo(f"✔ scaffolded {kind} project in {name}/ — edit agentrum.yaml, then: agentrum apply {name}/agentrum.yaml")


@app.command()
def export(
    output: Path = typer.Option(Path("agentrum-bundle.yaml"), "-o", "--output"),
    kind: str | None = typer.Option(None, "--kind"),
    namespace: str | None = typer.Option(None, "-n", "--namespace"),
) -> None:
    """Export resources (all versions) as an apply-able YAML bundle.

    Used to promote content between environments (test -> prod registry):
    point ARK_SERVER/credentials at the target registry and `agentrum apply`
    the bundle. Secret values are never exported (keys only).
    """
    with httpx.Client(base_url=_server(), headers=_headers(), timeout=60) as client:
        params: dict = {"limit": 200}
        if kind:
            params["kind"] = kind
        if namespace:
            params["namespace"] = namespace
        resp = client.get("/v1/resources", params=params)
        if resp.status_code != 200:
            typer.echo(_detail(resp), err=True)
            raise typer.Exit(1)
        items = resp.json()["items"]
        total = resp.json().get("total", len(items))
        if total > len(items):
            typer.echo(
                f"! {total - len(items)} resource(s) beyond the first page were "
                "not exported; narrow with --kind/-n and re-run",
                err=True,
            )
        if not items:
            typer.echo("nothing to export")
            return

        docs: list[dict] = []
        secret_count = 0
        for it in items:
            if it["kind"] == "Secret":
                secret_count += 1
                docs.append(
                    {
                        "kind": "Secret",
                        "metadata": {"name": it["name"], "namespace": it["namespace"]},
                        "spec": {"data": {}},  # values intentionally omitted
                        "description": it.get("description"),
                        "visibility": it["visibility"],
                        "_note": "SECRET VALUES NOT EXPORTED — re-enter them at the target",
                    }
                )
                continue
            versions_resp = client.get(
                f"/v1/resources/{it['kind']}/{it['namespace']}/{it['name']}/versions"
            )
            versions = versions_resp.json() if versions_resp.status_code == 200 else []
            for v in reversed(versions):  # oldest → newest so replay order is correct
                docs.append(
                    {
                        "kind": it["kind"],
                        "metadata": {"name": it["name"], "namespace": it["namespace"], "labels": it.get("labels") or {}},
                        "spec": v["spec"],
                        "tag": v.get("tag"),
                        "change_notes": v.get("change_notes"),
                        "description": it.get("description"),
                        "visibility": it["visibility"],
                    }
                )
        with output.open("w") as fh:
            yaml.safe_dump_all(docs, fh, sort_keys=False, allow_unicode=True)
        typer.echo(
            f"✔ exported {len(docs)} document(s) from {len(items)} resource(s) "
            f"({secret_count} secret(s) value-stripped) -> {output}"
        )
