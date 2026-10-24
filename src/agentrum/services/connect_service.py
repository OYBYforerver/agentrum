"""Connection snippets: turn a published MCPServer entry into ready-to-paste
client configuration. The registry's whole point is "find it, then use it" —
this closes the gap between the catalog entry and the IDE config."""

import shlex

from agentrum import errors
from agentrum.db import models

SECRET_PLACEHOLDER = "<secret>"


def _split_env(entries: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Split env/header entries into literal values and secret-backed names.
    Secret-backed ones never leave the registry; consumers get a note."""
    values: dict[str, str] = {}
    secrets: list[str] = []
    for entry in entries or []:
        name = entry.get("name")
        if not name:
            continue
        if entry.get("value") is not None:
            values[name] = str(entry["value"])
        else:
            secrets.append(name)
    return values, secrets


def _secret_note(what: str, names: list[str]) -> list[str]:
    return [
        f"{what} {name} references a registry Secret — configure it in your "
        "client from your own secret store (registry values never leave the server)."
        for name in names
    ]


def build(resource: models.Resource, spec: dict) -> dict:
    """Build the connection payload for one MCPServer entry."""
    if resource.kind != "MCPServer":
        raise errors.ValidationError("connection snippets are only available for MCPServer")
    transport = spec.get("transport", "streamable-http")
    name = resource.name

    stdio: dict | None = None
    remote: dict | None = None
    notes: list[str] = []

    if transport == "stdio":
        env, env_secrets = _split_env(spec.get("env") or [])
        notes += _secret_note("env var", env_secrets)
        command = spec.get("command", "")
        args = list(spec.get("args") or [])
        stdio = {"command": command, "args": args, "env": env}
        clients = {
            "claude_code": f"claude mcp add {shlex.quote(name)} -- "
                           + " ".join(shlex.quote(p) for p in [command, *args]),
            "cursor": {"mcpServers": {name: {"command": command, "args": args, "env": env}}},
            "generic": {"mcpServers": {name: {"command": command, "args": args, "env": env}}},
        }
    else:
        header_values, header_secrets = _split_env(spec.get("headers") or [])
        notes += _secret_note("header", header_secrets)
        url = str(spec.get("endpoint") or "")
        remote = {"url": url, "type": "http" if transport == "streamable-http" else "sse",
                  "headers": header_values}
        header_flags = " ".join(
            f"--header {shlex.quote(f'{k}: {v}')}" for k, v in header_values.items()
        )
        transport_flag = "http" if transport == "streamable-http" else "sse"
        clients = {
            "claude_code": (
                f"claude mcp add --transport {transport_flag} {shlex.quote(name)} {shlex.quote(url)}"
                + (f" {header_flags}" if header_flags else "")
            ),
            "cursor": {"mcpServers": {name: {"url": url, "headers": header_values}}},
            "generic": {"mcpServers": {name: {"url": url}}},
        }

    return {
        "kind": resource.kind,
        "namespace": resource.namespace,
        "name": name,
        "transport": transport,
        "stdio": stdio,
        "remote": remote,
        "clients": clients,
        "notes": notes,
    }
