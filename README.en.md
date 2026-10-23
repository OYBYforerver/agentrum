# Agentrum

<p align="center">
  <img src="docs/logo/logo-horizontal.svg" alt="Agentrum" width="560"/>
</p>

**A multi-tenant registry for AI assets — agents, MCP servers, skills and prompts. Publish, subscribe, run.**

[中文说明见 README.md](README.md)

## Why Agentrum?

AI assets inside an organization end up scattered across repos, chat threads and laptops. Agentrum gives every team one place to **publish** their agents, MCP servers, skills and prompts — and lets other teams **subscribe** to them, get notified on new versions, and **deploy** them to Kubernetes.

- **Multi-tenant by design** — every team owns a namespace; publishers, members and platform admins have distinct roles
- **Cross-team subscriptions** — internal resources are visible org-wide; `restricted` resources require owner-team approval
- **Immutable versions** — tags never move; every publish is a new version with change notes
- **Deploy to Kubernetes** — a native reconciler runs your agents/MCP servers (image allowlist enforced), no sidecar framework required
- **Secrets with envelope encryption** — `env.valueFrom.secretRef`, values never returned by the API
- **SSO via standard OIDC** — any discovery-capable IdP (Keycloak, Okta, Casdoor, …) plus a built-in Feishu preset; local accounts for bootstrap
- **Bilingual** — UI, docs and this README ship in English and Chinese

## Acknowledgements

> **Agentrum is rebuilt from the architecture of the open-source [agentregistry](https://github.com/agentregistry-dev/agentregistry) project — full credit and thanks to its authors and community.**
>
> The core design ideas — a Kubernetes-style declarative resource model (`apply/get/delete`), immutable tags, soft delete, labels, the reconciliation pattern, and exposing the registry itself over MCP — come from agentregistry. Agentrum is a **fresh Python implementation** (FastAPI + SQLAlchemy + PostgreSQL); no upstream code was copied. All implementation mistakes are ours.

## Quick start

```bash
git clone https://github.com/agentrum/agentrum && cd agentrum
docker compose up -d --wait        # PostgreSQL + server on :12122
open http://localhost:12122/docs   # OpenAPI
```

Default bootstrap admin: `admin` / `admin123` (override `ARK_BOOTSTRAP_ADMIN_*` — **change it before any real use**).

## One-minute tour

```bash
pip install agentrum  # or: uv tool install agentrum
agentrum login --server http://localhost:12122 --username admin
agentrum init mcp-server payment-gateway && cd payment-gateway
# edit agentrum.yaml, then:
agentrum apply agentrum.yaml
agentrum get MCPServer -n default
```

Teams, subscriptions and approvals work the same way via the REST API — see the [docs](#documentation) or the OpenAPI UI.

## Kubernetes (production)

```bash
helm upgrade --install agentrum charts/agentrum \
  --set database.url="postgresql+asyncpg://user:pass@db:5432/agentrum" \
  --set auth.secretKey="$(openssl rand -hex 32)" \
  --set auth.bootstrapAdminPassword="$(openssl rand -hex 16)" \
  --set deploy.imageAllowlist="registry.internal/,ghcr.io/acme/" \
  --set secrets.encryptionKey="$(openssl rand -base64 32)"
```

Two replicas by default, migrations run in an init container, readiness/liveness probes wired, controller RBAC is namespace-scoped.

## Documentation

- 中文文档 / English docs: `mkdocs serve` (see `mkdocs.yml`) — bilingual docs site built with mkdocs-material
- Roadmap & decisions: [docs/ROADMAP.md](docs/ROADMAP.md), [docs/RESEARCH-resource-model.md](docs/RESEARCH-resource-model.md)

## Security

See [SECURITY.md](SECURITY.md). Please report vulnerabilities privately; do not open public issues for security problems.

## License

Apache-2.0. Design inspired by [agentregistry](https://github.com/agentregistry-dev/agentregistry) (Apache-2.0).
