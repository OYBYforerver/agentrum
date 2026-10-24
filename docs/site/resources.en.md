# Resource spec (agentrum.yaml)

All resources share one envelope: `kind + metadata + spec`, submitted via `agentrum apply` or `PUT /v1/resources/...`. Extra fields in `spec` are allowed (forward compatibility), but each kind enforces a minimal contract; every published version is stamped with a `spec_version` field so shape evolution is detectable.

Editor support: add `$schema: http://<server>/v1/schema/manifest.json` to your agentrum.yaml (public endpoint, no credentials needed) and yaml-language-server will validate/complete the manifest. Templates from `agentrum init` carry the key already.

```yaml
kind: MCPServer
$schema: http://localhost:12122/v1/schema/manifest.json
metadata:
  name: payment-gateway        # lowercase/digits/-; unique per (kind, namespace, name)
  namespace: payment           # owning project namespace
  labels: {team: payment}
spec:                          # per-kind payload, see table
  transport: streamable-http
  endpoint: http://pg.payment:3000/mcp
tag: v1.2.0                    # immutable: re-publishing the same tag → 409
change_notes: what changed     # sent to subscribers
description: Payment gateway MCP
visibility: internal           # internal | restricted (prompts forced private)
catalog:                       # mutable catalog metadata (no new version)
  title: Payment Gateway
  long_description: "Markdown long description…"
  keywords: [payment, mcp]
  authors: [alice]
  license: Apache-2.0
  links: {docs: "https://...", source: "https://..."}
```

## Per-kind spec contracts

| kind | Required | Common optional | Notes |
|---|---|---|---|
| `Agent` | `image` | `framework`, `protocol` (`mcp/a2a/openapi/http/custom`), `agent_card_url` (A2A card, required when protocol=a2a), `capabilities[]`, `env[]` | env entry: `{name, value}` or `{name, value_from: {secret_ref: {name, key}}}`; cluster placement (namespace/replicas) belongs to the Deployment |
| `MCPServer` | `transport` + (`endpoint` or `command`) | `args[]` (stdio only, e.g. the args of `npx -y @mcp/xxx`), `headers[]` (remote auth headers, same shape as env entries, values may reference Secrets), `env[]` | transport ∈ `streamable-http / sse / stdio`; http kinds require endpoint, stdio requires command and forbids args |
| `Skill` | `source.git.url` or `instructions` (either) | `entrypoint`, `source.git.ref/subdirectory/credentials_ref` | see git-source section |
| `Prompt` | `template` | `variables[]` (`{name, required, description}`) | **project-private**; every `{{placeholder}}` in the template must be declared — and every declared variable used — or publishing is rejected |

Declared variables power structured forms in the console and structured MCP consumption:

```yaml
kind: Prompt
metadata: {name: review-checklist, namespace: payment}
spec:
  template: "Review this change, focus on {{concerns}}"
  variables:
    - {name: concerns, required: true, description: risk areas to focus on}
    - {name: code, description: the code}
```
| `Secret` | `data` (key/value object) | — | values envelope-encrypted, never returned; always `restricted` |
| `Deployment` | `target_kind/target_namespace/target_name` | `tag` (pin), `cluster_namespace`, `replicas`, `port`, `image_pull_policy` | see Deploy to Kubernetes |

## Env vars & Secret references

```yaml
kind: Agent
metadata: {name: fraud-detection, namespace: payment}
spec:
  image: registry.internal/fraud:1.0
  env:
    - {name: LOG_LEVEL, value: info}
    - name: API_KEY
      value_from:
        secret_ref: {name: api-keys, key: API_KEY}   # same-project Secret
```

## Visibility model

| visibility | Who can read | Cross-project subscription |
|---|---|---|
| `internal` | All authenticated users | Active immediately |
| `restricted` | Owning project + subscribed projects | Owner-team admin approval |
| `private` (Prompt only) | Owning project members only | Not allowed |

Publishing requires the `publisher`/`admin` role in the owning namespace, or a project AK/SK with the `publish` scope. Versions are monotonic, tags immutable; soft-deleted resources are restored by re-applying.

## Git-backed skills

Skill content is best kept in git; the registry stores a pointer plus the pinned commit SHA:

```yaml
kind: Skill
metadata: {name: gateway-skill, namespace: payment}
spec:
  source:
    git:
      url: https://git.internal/pay/skills.git
      ref: main                      # branch / tag / full commit SHA
      subdirectory: skills/gateway   # optional
      credentials_ref: git-creds     # optional: Secret with username/password or token
  entrypoint: SKILL.md               # optional entry file inside the repo
```

At publish time the server resolves `ref` to a **commit SHA and locks it into the immutable version** — even when `ref` names a branch, the version records where upstream stood at publish time. Unresolvable sources (unreachable repo, missing ref, bad credentials) block the publish. Background drift detection (`ARK_SKILL_DRIFT_INTERVAL_SECONDS`, default 300s, 0 disables) marks an `UpstreamDrift` condition when upstream moves — it **never rewrites versions**; re-publish to catch up. SSH is not supported yet; HTTPS + token credentials cover internal GitLab/GitHub.

At publish time the entrypoint file (default `SKILL.md`) is also **snapshotted into the version spec** (`entrypoint_snapshot`: path, content, parsed frontmatter), so published versions stay self-contained even if the upstream repo disappears. When SKILL.md carries standard frontmatter: `name` must match the resource name and `description` is required (Anthropic skill format) — mismatches are rejected at publish.

## MCP Server connection snippets

From catalog entry to working client config in one call:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://<server>/v1/resources/MCPServer/payment/payment-gateway/connect
```

Returns the `transport`, the stdio launch (`command/args/env`) or remote `url/headers`, plus three ready-to-paste client configs: `clients.claude_code` (an executable `claude mcp add ...` line), `clients.cursor` and `clients.generic` (standard `mcpServers` JSON). Env/headers backed by registry Secrets are **never** included in the snippet — they surface in `notes` instead, telling consumers to configure them client-side. The MCP channel (`get_resource` tool) carries the same `connect` block for in-IDE consumption.

## Deprecation

Soft-delete is not the only way to retire a resource: **deprecate** it first — the resource stays visible and consumable, subscribers receive a `resource.deprecated` notification, and the catalog/MCP listing carry the deprecation flag:

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -d '{"deprecated": true, "deprecation_reason": "superseded", "successor": "payment/payment-gateway-v2"}' \
  https://<server>/v1/resources/Agent/payment/payment-gateway
```

`successor` optionally points at the replacement; `deprecated: false` clears the marker. Deprecation notices go to all active subscribers regardless of their `events` preferences — it is an impact warning about content they already consume. The console shows a deprecation banner on the detail page.
