# IDE integration (MCP)

The Agentrum registry is itself an MCP server — Cursor, Claude Code, Cline and other MCP clients can ask the registry directly: which MCP servers / agents are available, what are their endpoints, what is the latest version. Read-only tool surface; permissions match the console exactly (JWT or project AK/SK).

## Endpoint & auth

```
Streamable HTTP:  http://<registry-host>:12122/mcp
Auth:             Authorization: Bearer <JWT>   or   Authorization: Basic <AK>:<SK> (base64)
```

Give your IDE a read-only (`read` scope) project AK/SK: console → project → Settings → AK/SK.

## Cursor / Claude Code config

```json
{
  "mcpServers": {
    "agentrum": {
      "url": "http://localhost:12122/mcp",
      "headers": {
        "Authorization": "Basic <base64(AK:SK)>"
      }
    }
  }
}
```

## Exposed tools

| Tool | Purpose |
|---|---|
| `registry_overview` | visible resource counts per kind + server version |
| `list_resources` | browse the catalog by kind/namespace/keyword (visibility-filtered) |
| `get_resource` | one resource: latest (or pinned) spec, endpoint, change notes, catalog metadata |
| `list_prompts` | prompt templates visible to you (prompts are project-private), with declared variables |
| `get_prompt` | fetch a template; or render server-side with `variables_json` (required/unknown variables validated) |

Typical flow: ask the IDE "which payment-related MCP servers are in the registry?" — the client calls `list_resources(search=payment)`, then `get_resource` for the endpoint and version, ready to wire into config.

!!! note "Visibility is the permission"
    Tool output matches what the calling principal sees in the console: an AK/SK sees its own project plus subscriptions, internal resources are org-wide, Prompts stay project-private.
