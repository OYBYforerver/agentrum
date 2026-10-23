<p align="center">
  <img src="docs/logo/logo-horizontal.svg" alt="Agentrum" width="560"/>
</p>

<h1 align="center">Agentrum</h1>

<p align="center">
  <strong>多租户的企业级 AI 资产注册中心</strong> — 在一个地方注册、发现、订阅和部署
  <br/>AI Agent、MCP Server、Skill 与 Prompt
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"/>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python"/>
  <img src="https://img.shields.io/badge/API-FastAPI-teal" alt="FastAPI"/>
</p>

---

## 致谢与致敬(Acknowledgements)

> **本项目基于开源项目 [agentregistry](https://github.com/agentregistry-dev/agentregistry) 重构而来,在此向原作者与社区致敬。**
>
> - Agentrum 的核心设计思想 —— Kubernetes 风格的声明式资源模型(`apply / get / delete`)、不可变 tag 版本、软删除、labels、控制器调和模式、注册中心自身暴露 MCP Server —— 都源自 agentregistry 项目,我们站在它的肩膀上。
> - Agentrum 是**全新实现**:使用 Python(FastAPI + SQLAlchemy + PostgreSQL)重写,未复制任何上游代码。数据模型与 API 契约的灵感归属原作者,实现中的所有错误归我们。
> - 上游采用 Go 语言实现,因团队技术栈原因我们选择以 Python 重建,并聚焦企业内部使用场景(多租户、订阅、审计)。

## 这是什么

团队内的 AI 资产(Agent、MCP Server、Skill、Prompt)散落在各处,没人知道哪些可信、哪个版本能用。Agentrum 把它们收进一个注册中心:

- **多租户**:每个项目组(Team)拥有自己的命名空间(Namespace),在各自的命名空间里发布内容,互不干扰
- **相互订阅**:项目组之间可以订阅彼此的目录;资源默认全公司可见,敏感资源可标记为 `restricted`,订阅需属主团队审批
- **版本追溯**:tag 一经发布不可变,随时取回任意历史版本
- **审计**:所有发布、订阅、审批、删除动作都有审计记录,可归因到人

## 快速开始

前置要求:Docker(Docker Compose v2)。

```bash
git clone <your-repo-url> agentrum && cd agentrum
docker compose up -d --wait
```

打开 <http://localhost:12122/docs> 查看 OpenAPI 文档;双语管理界面(中文/English)构建与部署:

```bash
cd ui && npm install && npm run build   # 静态产物在 ui/out/,任意静态服务器托管
```

生产部署(K8s 双副本 + 迁移 initContainer + 镜像白名单)见 `charts/agentrum` 与 [docs/site](docs/site)。初始管理员账号由环境变量 `ARK_BOOTSTRAP_ADMIN_USERNAME` / `ARK_BOOTSTRAP_ADMIN_PASSWORD` 控制(默认 `admin` / `admin123`,**生产环境务必修改**)。

只想本地跑(不进容器):

```bash
make compose-up   # 仅启动 PostgreSQL
make migrate      # 执行数据库迁移
make serve        # uvicorn 启动在 :12122
```

## 一分钟体验核心流程

```bash
# 0) 管理员登录
TOKEN=$(curl -s localhost:12122/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

# 1) 创建两个项目组(自动获得同名命名空间,创建者成为组管理员)
curl -s localhost:12122/v1/teams -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"payment","display_name":"支付平台组"}' > /dev/null
curl -s localhost:12122/v1/teams -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"support","display_name":"客服智能组"}' > /dev/null

# 2) 支付组发布一个 MCP Server,打上不可变 tag
curl -s -X PUT localhost:12122/v1/resources/MCPServer/payment/payment-gateway \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"spec":{"transport":"streamable-http","endpoint":"http://payment-gateway.payment.svc:3000/mcp"},"tag":"v1.2.0","description":"支付网关 MCP"}' | python3 -m json.tool

# 3) 客服组订阅支付组的这个服务(默认 internal,直接生效)
curl -s localhost:12122/v1/teams/support/subscriptions \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"kind":"MCPServer","namespace":"payment","name":"payment-gateway"}' | python3 -m json.tool

# 4) 审计流水(平台管理员)
curl -s "localhost:12122/v1/audit?limit=5" -H "$AUTH" | python3 -m json.tool
```

若资源发布时指定 `"visibility":"restricted"`,第 3 步的订阅会进入 `pending_approval` 状态,由支付组管理员通过 `/v1/subscriptions/{id}/approve` 审批。

## 架构

```
agentrum/
├── src/agentrum/
│   ├── api/            # FastAPI 路由(薄,只做协议转换)
│   ├── services/       # 业务逻辑:租户、资源可见性、订阅审批
│   ├── db/             # SQLAlchemy 模型 + 异步引擎(唯一触碰数据库的层)
│   ├── auth/           # 本地账号 + JWT + API Token(后续接 OIDC)
│   ├── schemas/        # Pydantic 请求/响应模型
│   ├── audit.py        # 审计日志
│   └── main.py         # 应用工厂
├── migrations/         # Alembic 迁移
├── tests/
├── docs/logo/
├── Dockerfile
└── docker-compose.yml  # PostgreSQL + Server
```

## 多租户与订阅模型

```
平台 (platform admin)
└── 项目组 Team            ← 成员角色: admin / publisher / member
    └── 命名空间 Namespace  ← 隔离单元,建组时自动创建
        └── 资源 (kind + namespace + name 全局唯一)
            └── 版本 (version 单调递增, tag 不可变)
```

| 资源可见性 | 谁能读 | 跨团队订阅 |
|---|---|---|
| `internal`(默认) | 全部登录用户 | 直接生效 |
| `restricted` | 属主团队 + 已订阅团队 | 需属主团队 admin 审批 |

发布需要属主命名空间的 `publisher` 或 `admin` 角色;删除同理(软删除,重新 apply 即恢复)。

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `ARK_DATABASE_URL` | `postgresql+asyncpg://agentrum:agentrum@localhost:5433/agentrum` | PostgreSQL 连接串 |
| `ARK_SECRET_KEY` | `dev-insecure-change-me` | JWT 签名密钥,**生产必须修改** |
| `ARK_ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | 登录会话有效期 |
| `ARK_BOOTSTRAP_ADMIN_USERNAME` | `admin` | 首次启动创建的平台管理员 |
| `ARK_BOOTSTRAP_ADMIN_PASSWORD` | `admin123` | 同上,**生产必须修改** |
| `ARK_ALLOWED_ORIGINS` | `*` | CORS 来源,逗号分隔;生产务必收敛 |
| `ARK_LOG_FORMAT` | `console` | 日志格式:`console` / `json`(生产建议 json) |
| `ARK_MAX_BODY_BYTES` | `2097152` | 请求体大小上限(2 MiB) |
| `ARK_FEISHU_WEBHOOK_URL` | 空 | 飞书群自定义机器人 webhook,配置后推送订阅事件 |
| `ARK_FEISHU_WEBHOOK_SECRET` | 空 | 机器人签名密钥(可选) |
| `ARK_NOTIFICATION_WEBHOOK_URL` | 空 | 通用 webhook(HMAC 签名头 `X-Agentrum-Signature`) |

## 路线图

完整路线图与决策记录见 [docs/ROADMAP.md](docs/ROADMAP.md)。里程碑:

- [x] **M1**:本地账号认证、团队/命名空间、资源发布与版本、订阅与审批、审计日志
- [ ] **阶段 A(进行中)**:安全加固(限流/CORS/readyz/结构化日志)、用户治理、飞书订阅通知、CI
- [ ] **阶段 B**:OIDC SSO(飞书 Provider)、K8s 部署控制器 + Secret 管理、双语 UI、搜索、可观测性
- [ ] **阶段 C**:开源发布(双语文档站、发布流水线、多环境提升)

## License

Apache-2.0。设计思想致敬 [agentregistry](https://github.com/agentregistry-dev/agentregistry)(Apache-2.0)。
