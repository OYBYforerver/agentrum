<p align="center">
  <img src="docs/logo/logo-horizontal.svg" alt="Agentrum" width="520"/>
</p>

<h1 align="center">Agentrum</h1>

<p align="center">
  <strong>A multi-tenant registry for AI assets</strong><br/>
  One home for your team's agents, MCP servers, skills and prompts — publish, subscribe, run.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"/>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python"/>
  <img src="https://img.shields.io/badge/API-FastAPI-teal" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/MCP-native-purple" alt="MCP"/>
  <a href="README.md"><img src="https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-red" alt="中文"/></a>
</p>

---

## The problem it solves

AI assets end up scattered across chat threads, laptops and repos: nobody knows which are trustworthy, which version works, how to run them. Agentrum gives every project team **their own space** to publish assets, gives other teams a **subscription channel with approval**, and manages the Kubernetes deployment part too.

| | |
|---|---|
| ![Overview](docs/img/01-overview.png) | ![Catalog](docs/img/02-catalog.png) |
| *Project overview: resources, releases, subscribers, approvals at a glance* | *Catalog: organized by kind, visibility badges for internal / restricted / private* |
| ![Detail](docs/img/03-detail.png) | ![Publish](docs/img/04-publish.png) |
| *Resource detail: health, spec, version timeline* | *Publish: kind-specific forms, immutable tags* |
| ![Subscribe](docs/img/05-subscribe.png) | ![Dark](docs/img/06-dark.png) |
| *Cross-team subscribe: searchable picker — type `pay` to filter* | *Dark mode (light default, one-click toggle)* |

## Highlights

- **Multi-tenant projects** — provisioned by platform admins; admin / publisher / member roles per project
- **AK/SK machine credentials** — registration, discovery and consumption all carry project-scoped keys; scopes gate read/publish/deploy; SK shown once, revocable
- **Cross-project subscriptions** — `internal` is instant; `restricted` needs owner approval; **prompts stay project-private**
- **Immutable versions** — tags never move; every release carries change notes and notifies subscribers
- **Native K8s deploys** — `Deployment` resource + reconciler; the image allowlist guards the "publish ≈ code execution" boundary
- **The registry is an MCP server** — point Cursor / Claude Code at `/mcp` and discover company assets inside your IDE
- **Git-backed skills** — commit SHA pinned at publish, upstream drift flagged automatically
- **Envelope-encrypted secrets** — values never returned; `env.secretRef` injects into deployments
- **SSO** — standard OIDC (any IdP) + Feishu preset; local accounts only for bootstrap
- **Bundled bilingual handbook** — linked from the console; interactive API docs at `/docs`

## Architecture

<p align="center"><img src="docs/img/architecture.svg" alt="Agentrum architecture" width="820"/></p>

Control plane, not data plane: deployed workloads run independently; consumers cache resolutions and tolerate registry blips.

## Quick start

```bash
docker compose up -d --wait          # PostgreSQL + server (API :12122, docs :12122/handbook/)
open http://localhost:12122/handbook
```

Publish your first asset:

```bash
pip install agentrum                 # or: uv sync && uv run agentrum
agentrum login --server http://localhost:12122 --username admin
agentrum init mcp-server payment-gateway && cd payment-gateway
agentrum apply agentrum.yaml
agentrum get MCPServer
```

Bootstrap account `admin / admin123` (**change before any real use**).

## Production (Kubernetes)

```bash
helm upgrade --install agentrum charts/agentrum \
  --set database.url="postgresql+asyncpg://user:pass@db:5432/agentrum" \
  --set auth.secretKey="$(openssl rand -hex 32)" \
  --set auth.bootstrapAdminPassword="$(openssl rand -hex 16)" \
  --set secrets.encryptionKey="$(openssl rand -base64 32)" \
  --set deploy.imageAllowlist="registry.internal/,ghcr.io/acme/" \
  --set ingress.enabled=true --set ingress.host=registry.internal
```

Two replicas, initContainer migrations, readiness probes, namespace-scoped controller RBAC. See the [operations handbook](docs/site/operations.en.md).

## Documentation

| You are… | Start here |
|---|---|
| Publishing developer | [Quick start](docs/site/quickstart.md) · [CLI reference](docs/site/cli.md) · [Resource spec](docs/site/resources.md) |
| Scripts / CI | [API reference](docs/site/api.md) · [IDE integration (MCP)](docs/site/ide.md) |
| Project admin | [Subscribe & notifications](docs/site/subscribe.md) · [SSO setup](docs/site/sso.md) |
| Platform / SRE | [Deploy to K8s](docs/site/deploy.md) · [Operations handbook](docs/site/operations.en.md) |

Also served by the app at `/handbook/` and `/docs`.

## Acknowledgements

> **Agentrum is rebuilt on the architecture of the open-source [agentregistry](https://github.com/agentregistry-dev/agentregistry) project — full credit to its authors and community.**
>
> The Kubernetes-style declarative resource model, immutable tags, soft delete, the reconciliation pattern and the registry-as-MCP-server idea all come from agentregistry. Agentrum is a **fresh Python implementation** (FastAPI + SQLAlchemy + PostgreSQL); no upstream code was copied. Implementation mistakes are ours.

## License

[Apache-2.0](LICENSE)
