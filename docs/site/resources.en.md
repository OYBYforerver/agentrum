# Resource spec (agentrum.yaml)

All resources share one envelope: `kind + metadata + spec`, submitted via `agentrum apply` or `PUT /v1/resources/...`. Extra fields in `spec` are allowed (forward compatibility), but each kind enforces a minimal contract.

```yaml
kind: MCPServer
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
| `Agent` | `image` | `framework`, `env[]` | env entry: `{name, value}` or `{name, value_from: {secret_ref: {name, key, namespace?}}}` |
| `MCPServer` | `transport` + (`endpoint` or `command`) | `env[]` | transport ∈ `streamable-http / sse / stdio`; http kinds require endpoint, stdio requires command |
| `Skill` | — | `entrypoint`, `instructions` | git-source mode (`source.git`) planned |
| `Prompt` | `template` | variable declarations planned | **project-private**; cross-project subscription rejected |
| `Secret` | `data` (key/value object) | — | values envelope-encrypted, never returned; defaults to `restricted` |
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
