# Quick start

Run locally, publish your first asset, subscribe across teams — 5 minutes.

## 1. 启动 / Run

```bash
docker compose up -d --wait
open http://localhost:12122/docs
```

Bootstrap admin: `admin` / `admin123`(生产环境务必修改)。

## 2. 发布第一个资源 / Publish

```bash
agentrum login --server http://localhost:12122 --username admin
agentrum init mcp-server payment-gateway && cd payment-gateway
# 编辑 agentrum.yaml → agentrum apply agentrum.yaml
agentrum apply agentrum.yaml
agentrum get MCPServer
```

## 3. 跨项目订阅 / Subscribe across projects

1. 另一项目成员:控制台「我的订阅 → 新建订阅」(可搜索选择),或
   `POST /v1/teams/{team-b}/subscriptions` 指定 `{kind, namespace, name}`
2. `internal` → 直接生效;`restricted` → 属主项目 admin 在「订阅申请」里批准
3. 之后每次发布新版本,订阅方通过飞书 / webhook 收到通知

## 4. 部署到集群 / Deploy

见 [部署接入](deploy.md):发布一个 `Deployment` 资源即可,控制器负责调和。

## 5. 生产部署 / Production

见 [运维手册](operations.md):Helm、环境变量、备份、可观测性。
