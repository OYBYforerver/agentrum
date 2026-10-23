"""Agentrum CLI — login, apply, get, delete against a registry server."""

import json
import os
import stat
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
    _CREDENTIALS.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _CREDENTIALS.write_text(json.dumps(data))
    _CREDENTIALS.chmod(stat.S_IRUSR | stat.S_IWUSR)


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
        typer.echo(f"login failed ({resp.status_code}): {resp.json().get('detail', resp.text)}", err=True)
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
                detail = resp.json().get("detail", resp.text)
                typer.echo(f"    {detail}", err=True)
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
                typer.echo(resp.json().get("detail", resp.text), err=True)
                raise typer.Exit(1)
            typer.echo(json.dumps(resp.json(), indent=2, ensure_ascii=False))
            return
        params: dict = {"kind": kind, "limit": 200}
        if namespace and not all_namespaces:
            params["namespace"] = namespace
        resp = client.get("/v1/resources", params=params)
        if resp.status_code != 200:
            typer.echo(resp.json().get("detail", resp.text), err=True)
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
) -> None:
    """Soft-delete a resource (re-apply restores it)."""
    namespace, _, name = ref.partition("/")
    if not namespace or not name:
        typer.echo("ref must be namespace/name", err=True)
        raise typer.Exit(1)
    with httpx.Client(base_url=_server(), headers=_headers(), timeout=30) as client:
        resp = client.delete(f"/v1/resources/{kind}/{namespace}/{name}")
        if resp.status_code == 204:
            typer.echo(f"✔ deleted {kind}/{namespace}/{name}")
        else:
            typer.echo(resp.json().get("detail", resp.text), err=True)
            raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show server version."""
    resp = httpx.get(f"{_server()}/health", timeout=10)
    typer.echo(json.dumps(resp.json(), ensure_ascii=False))


_INIT_TEMPLATES: dict[str, dict] = {
    "agent": {
        "kind": "Agent",
        "metadata": {"name": "my-agent", "namespace": "default", "labels": {}},
        "spec": {"image": "registry.internal/my-agent:0.1.0", "framework": "langgraph"},
        "description": "TODO: what does this agent do",
        "tag": "v0.1.0",
    },
    "mcp-server": {
        "kind": "MCPServer",
        "metadata": {"name": "my-server", "namespace": "default", "labels": {}},
        "spec": {"transport": "streamable-http", "endpoint": "http://localhost:3000/mcp"},
        "description": "TODO: tools exposed by this MCP server",
        "tag": "v0.1.0",
    },
    "skill": {
        "kind": "Skill",
        "metadata": {"name": "my-skill", "namespace": "default", "labels": {}},
        "spec": {"entrypoint": "SKILL.md", "instructions": "TODO: how to use this skill"},
        "description": "TODO: skill summary",
        "tag": "v0.1.0",
    },
    "prompt": {
        "kind": "Prompt",
        "metadata": {"name": "my-prompt", "namespace": "default", "labels": {}},
        "spec": {"template": "TODO: prompt template with {{variables}}"},
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
            typer.echo(resp.text, err=True)
            raise typer.Exit(1)
        items = resp.json()["items"]
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
