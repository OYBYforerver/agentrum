# Agentrum

**A multi-tenant registry for AI assets** — publish, subscribe to and run agents, MCP servers, skills and prompts.

Agentrum is rebuilt on the architecture of the open-source [agentregistry](https://github.com/agentregistry-dev/agentregistry) project — see the repo [README](https://github.com/agentrum/agentrum) for the full acknowledgement.

## Find docs by role

| You are… | Start here |
|---|---|
| A developer publishing assets | [Quick start](quickstart.md) → [CLI reference](cli.md) → [Resource spec](resources.md) |
| Writing scripts / CI / runtime | [API reference](api.md) (AK/SK auth, errors, pagination) |
| A project admin | [Subscribe & notifications](subscribe.md) → [SSO setup](sso.md) |
| Platform / SRE | [Deploy to K8s](deploy.md) → [Operations handbook](operations.md) |

## Three core concepts

1. **Project**: the isolation unit, provisioned by platform admins; members hold admin / publisher / member roles
2. **AK/SK**: project-scoped machine credentials — registration, discovery and consumption all carry them; scopes gate read/publish/deploy
3. **Subscription**: cross-team consumption with authorization + notifications; `internal` is instant, `restricted` needs owner approval, Prompts stay project-private

Interactive OpenAPI docs are served by the app at `/docs`.
