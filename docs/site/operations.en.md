# Operations handbook

## Environment variable reference

| Variable | Default | Purpose |
|---|---|---|
| `ARK_DATABASE_URL` | `postgresql+asyncpg://agentrum:agentrum@localhost:5433/agentrum` | PostgreSQL DSN (external HA instance in prod) |
| `ARK_SECRET_KEY` | `dev-insecure-change-me` | JWT signing key — **must change** |
| `ARK_SECRET_ENCRYPTION_KEY` | derived from SECRET_KEY (warns) | Secret envelope key (Fernet, 32-byte urlsafe b64) |
| `ARK_ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Session validity |
| `ARK_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` | `admin` / `admin123` | First-boot admin — **must change** |
| `ARK_ALLOWED_ORIGINS` | `*` | CORS allowlist (comma-separated) |
| `ARK_LOG_FORMAT` | `console` | `json` for log shippers |
| `ARK_MAX_BODY_BYTES` | `2097152` | Request body cap |
| `ARK_IMAGE_ALLOWLIST` | empty (dev only) | Deployment image prefixes, comma-separated |
| `ARK_FEISHU_WEBHOOK_URL/SECRET` | — | Feishu bot notifications |
| `ARK_NOTIFICATION_WEBHOOK_URL/SECRET` | — | Generic webhook (`X-Agentrum-Signature` header) |
| `ARK_OIDC_GENERIC_ISSUER/CLIENT_ID/CLIENT_SECRET` | — | Generic OIDC |
| `ARK_RATELIMIT_BACKEND` | `memory` | `redis` shares login rate limits/lockouts across replicas (needs `agentrum[redis]`; fails open with a warning if Redis is down) |
| `ARK_RATELIMIT_REDIS_URL` | `redis://localhost:6379/0` | Rate-limit backend address |
| `ARK_EGRESS_ALLOW_PRIVATE_ADDRESSES` | `true` | Whether server-initiated outbound requests (git fetch, health probes, content delivery) may reach private ranges (internal git servers usually need this) |
| `ARK_EGRESS_ALLOW_LOOPBACK` | `false` | Dev escape hatch: allow loopback/link-local (includes cloud metadata — refused by default) |
| `ARK_EGRESS_ALLOW_FILE_SOURCES` | `false` | Dev/test only: allow file:// git sources |
| `ARK_SKILL_CONTENT_MAX_BYTES` | `52428800` | Size cap for skill content tarballs |
| `ARK_RESOURCE_RETENTION_DAYS` | `30` | days a soft-deleted resource stays in the recycle bin before the retention prune removes it for good (versions and secret payloads cascade) |
| `ARK_FEISHU_APP_ID/APP_SECRET` | — | Feishu SSO |
| `ARK_OIDC_REDIRECT_BASE` / `ARK_UI_ORIGIN` | — | Callback base / UI redirect origin |
| `ARK_PROBE_INTERVAL_SECONDS` | `60` | MCPServer endpoint probe interval |
| `ARK_DEPLOY_INTERVAL_SECONDS` | `10` | Deploy reconcile interval |
| `ARK_AUDIT_RETENTION_DAYS` | `180` | Audit retention |
| `ARK_NOTIFICATION_RETENTION_DAYS` | `30` | Delivered-notification retention |
| `ARK_OTEL_ENABLED` / `ARK_OTELENDPOINT` | `false` | OTLP tracing (off by default) |

## Kubernetes deployment

```bash
helm upgrade --install agentrum charts/agentrum \
  --set database.url="postgresql+asyncpg://user:pass@db:5432/agentrum" \
  --set auth.secretKey="$(openssl rand -hex 32)" \
  --set auth.bootstrapAdminPassword="$(openssl rand -hex 16)" \
  --set secrets.encryptionKey="$(openssl rand -base64 32)" \
  --set deploy.imageAllowlist="registry.internal/" \
  --set ingress.enabled=true --set ingress.host=registry.internal
```

Notes: two replicas by default; **migrations run in an initContainer** (app pods never run alembic — no multi-replica races); `/readyz` includes a DB check; controller RBAC is namespace-scoped.

## Backup & restore

```bash
kubectl exec deploy/postgres -- pg_dump -U agentrum agentrum | gzip > backup-$(date +%F).sql.gz
gunzip -c backup-2026-10-24.sql.gz | psql -U agentrum agentrum
```

Secret values are envelope-encrypted — **back up `ARK_SECRET_ENCRYPTION_KEY` together with the dump**; losing the key means losing Secrets.

## Observability

- `/metrics`: Prometheus counters/histograms (HTTP volume/latency/status)
- `ARK_LOG_FORMAT=json`: structured logs with `request_id` (matches the `X-Request-ID` response header)
- `ARK_OTEL_ENABLED=true` + `ARK_OTEL_ENDPOINT`: OTLP tracing
- Probes: `/health` (process), `/readyz` (DB readiness)

## Consumer fault-tolerance contract (important)

The registry is a **control plane**, not a data plane: deployed agents/MCP servers run independently and never route traffic through it. Consumers should cache resolutions and retry around short registry outages — **do not make runtime startup hard-depend on the registry**, or a blip becomes a company-wide release freeze.
