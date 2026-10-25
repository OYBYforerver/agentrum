# CLI Reference

The `agentrum` CLI is the main entry point for developers and CI. Install with `pip install agentrum` (or `uv run agentrum` inside a source checkout).

## Two login modes

| Mode | Audience | Command | Credential |
|---|---|---|---|
| Account login | Humans (console-equivalent rights) | `agentrum login --server URL --username U` (password prompted) | JWT, 8h validity |
| AK/SK login | CI / scripts / runtime | `agentrum login --server URL --ak ARK-ak-xxx --sk ARK-sk-xxx` | HTTP Basic, constrained by project scopes |

Credentials live in `~/.agentrum/credentials.json` (chmod 0600). For CI prefer environment variables `AGENTRUM_SERVER` / `AGENTRUM_TOKEN` or `AGENTRUM_AK` / `AGENTRUM_SK` — nothing touches disk.

!!! note "Scope differences"
    AK/SK are **project-scoped**: they can only touch that project's namespace and only within the `read / publish / deploy` scopes chosen at creation. Management operations (creating projects, member management) require account login.

## Commands

```bash
agentrum login        # login (account or AK/SK)
agentrum apply FILE   # publish YAML manifests (--- separated, kubectl style)
agentrum get KIND     # list; agentrum get KIND NAME -n NS for one (JSON output)
agentrum delete KIND ns/name   # soft delete (re-applying restores)
agentrum init KIND NAME        # scaffold: agent | mcp-server | skill | prompt
agentrum export -o bundle.yaml # export resources (all versions) for promotion
agentrum configure --client cursor   # write the registry into an IDE MCP config
agentrum version      # server version
```

## Typical flow

```bash
agentrum init mcp-server payment-gateway && cd payment-gateway
# edit agentrum.yaml (see the Resource spec page), then:
agentrum apply agentrum.yaml
agentrum get MCPServer -n payment

# Promotion: point at the production registry and replay
agentrum export -o bundle.yaml -n payment
ARK_SERVER=https://registry.prod.internal ARK_AK=... ARK_SK=... agentrum apply bundle.yaml
```

!!! warning "Secrets are never exported"
    `agentrum export` strips Secret values (keys only) — re-enter them in the target environment.
