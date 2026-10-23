# Quick start

## Run locally (Docker)

```bash
docker compose up -d --wait
open http://localhost:12122/docs
```

Bootstrap admin: `admin` / `admin123` (override before real use).

## Publish your first asset

```bash
agentrum login --server http://localhost:12122 --username admin
agentrum init mcp-server payment-gateway
agentrum apply payment-gateway/agentrum.yaml
agentrum get MCPServer
```

## Subscribe across teams

1. Team B member: `POST /v1/teams/{team-b}/subscriptions` targeting the resource
2. `internal` → active immediately; `restricted` → owner-team admin approves
3. New versions push notifications (Feishu webhook / generic webhook)

## Production (Kubernetes)

```bash
helm upgrade --install agentrum charts/agentrum \
  --set database.url="postgresql+asyncpg://..." \
  --set deploy.imageAllowlist="registry.internal/" \
  --set auth.secretKey="$(openssl rand -hex 32)"
```
