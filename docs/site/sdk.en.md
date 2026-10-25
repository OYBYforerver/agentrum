# Python SDK (consumers)

The standard way for applications to consume registry assets at runtime: `agentrum.sdk`. Discovery, content fetching and template rendering through one entry point; a local cache keeps your application running when the registry is down — that is the control-plane promise.

## Install & credentials

```bash
pip install agentrum          # or no install at all: uvx agentrum … (CLI)
```

Credential resolution order: explicit arguments → `AGENTRUM_AK`/`AGENTRUM_SK` (or `AGENTRUM_TOKEN`) env vars → the local credentials written by `agentrum login`. Give applications a project AK/SK with the read scope (console → settings → AK/SK).

## resolve: one entry point for all kinds

```python
import agentrum.sdk as agentrum

registry = agentrum.Registry("https://registry.internal", ak=..., sk=...)

# MCP server: endpoint + connection headers, then any MCP client
server = registry.resolve("MCPServer/payment/payment-gateway")
#   server.endpoint, server.transport, server.headers (literal values only;
#   secretRef-backed headers never leave the registry — arrange those with
#   the owning team out-of-band)

# Agent: externally hosted ones carry spec.endpoint; controller-deployed
# ones expose service_url in the Ready condition (status.conditions[0])

# Skill: locked SHA + content
skill = registry.resolve("Skill/team/pay-skill")   # skill.sha
registry.fetch_skill("Skill/team/pay-skill", dest="./skills")

# Prompt: template + declared variables, rendered locally (missing
# required / unknown variables are errors)
prompt = registry.resolve("Prompt/team/review-style")
text = prompt.render(language="python")
```

## Caching & outage fallback

`resolve()` caches results on disk with a TTL (default 300s; `~/.agentrum/cache`, override with `AGENTRUM_CACHE_DIR` or `cache_dir`). When the registry is unreachable you get the **stale cached copy** (`resolved.stale == True`); 4xx responses (bad credentials, no such resource) raise instead — those are real problems that stale data should not hide.

## Skill content delivery

```python
registry.fetch_skill("Skill/team/pay-skill", dest="./skills")
```

The registry fetches at the locked SHA **with its own stored credentials** and streams a tarball — subscribers of private repositories get the bytes while the credentials never leave the registry. Extraction uses tarfile's `data` filter; member paths escaping the destination are refused.

Equivalent REST call: `GET /v1/resources/Skill/{ns}/{name}/content?tag=…` (response header `X-Agentrum-Sha` carries the locked commit).

## MCP tool surface (in the IDE)

Besides `list_resources` / `get_resource`, `/mcp` exposes prompt tools:

| Tool | What it does |
|---|---|
| `list_prompts` | Prompts visible to you (prompts are project-private), with declared variables |
| `get_prompt` | Without `variables_json`: template + variables; with it: server-side rendering (required/unknown variables validated) |

IDE agents can use governed prompts directly; management actions (publish/version/approve) stay in the console and CLI.
