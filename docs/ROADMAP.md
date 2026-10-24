# Agentrum 路线图(定稿)

> 状态(2026-10-24):**阶段 A/B/C 主体全部落地**,版本 0.0.1(首次公开发布)。
> 本版包含:稳定错误码({code, detail})、注册中心自身 MCP 工具面(/mcp,IDE 接入)、项目概览指标、目录元数据 UI(发布/详情)、资源详情页、Prompt 变量声明、Skill git 来源(SHA 锁定 + 漂移检测)、项目制控制台 + AK/SK。诚实标注三处待真环境验证:K8s 部署控制器未在真实集群上跑通(逻辑经单测与本地 Postgres 调和验证);OIDC 完整握手需真实 IdP(端点/流程按标准与飞书文档实现);UI 为功能完整的 v0(目录/发布/订阅/审批/双语),深度打磨留待试点反馈。

## 决策记录

## 阶段 A — 内部试运行可用(进行中)

| 项 | 状态 |
|---|---|
| 登录限流 + 失败锁定(内存版,多副本可换 Redis) | ✅ |
| CORS 配置化(ARK_ALLOWED_ORIGINS) | ✅ |
| /readyz(含数据库探活,与 /health 分离) | ✅ |
| JSON 结构化日志 + X-Request-ID 贯穿 | ✅ |
| 请求体大小限制 | ✅ |
| 用户治理:改密码 / 禁用用户(API token 同步失效) | ✅ |
| per-kind spec 校验(Agent/MCPServer/Skill/Prompt) | ✅ |
| 订阅事件通知:事务性 outbox + 后台投递(飞书群机器人 webhook + 通用 webhook HMAC 签名) | ✅ |
| CI(GitHub Actions:ruff + pytest + 镜像构建) | ✅ |
| testcontainers 集成测试 | ✅(改为环境门控 + CI service container,`make test-integration`) |
| CLI 基础命令(login / apply / get / delete / version) | ✅ |
| 资源模型增强研究 | ✅ 结论见 [RESEARCH-resource-model.md](RESEARCH-resource-model.md):P0 = 目录元数据 + env.secretRef + 版本 changelog(部署控制器前置) |

## 阶段 B — 集群生产 ✅(2026-10-24)

- ✅ 资源模型增强:catalog 元数据列(npm/PyPI 对齐)+ `env[].valueFrom.secretRef` + 版本 `change_notes`
- ✅ Secret 类型 + Fernet 信封加密(值永不出库)
- ✅ OIDC SSO:通用 discovery(authlib JWKS 验签)+ 飞书预设(OAuth2 + user_info),JIT 建号,state-cookie 防 CSRF
- ✅ K8s 部署控制器:Deployment 资源 + 级别触发调和循环 + 可插拔适配器(kubernetes-asyncio 原生)+ 镜像白名单;RBAC 模板按命名空间最小授权
- ✅ Helm Chart:双副本 + initContainer 迁移 + readiness/liveness + Ingress 可选(helm template 验证通过)
- ✅ 健康探测(MCPServer 端点 → status conditions);消费方图谱 API + 删除级联通知
- ✅ pg_trgm 搜索索引;/metrics(Prometheus);OTel tracing(环境变量开启);审计/outbox 保留策略
- ✅ 双语 UI v0(Next.js 静态导出 + react-i18next:登录/目录/发布/订阅审批,中英切换)

## 阶段 C — 开源发布 ✅(2026-10-24)

- ✅ README.en / CONTRIBUTING(DCO)/ SECURITY.md / CODE_OF_CONDUCT / PR 模板
- ✅ mkdocs-material + mkdocs-static-i18n 双语文档站(CI 自动部署 gh-pages)
- ✅ 发布流水线:tag 触发 ghcr 镜像 + cosign keyless 签名 + Helm chart 随 Release 发布
- ✅ 多环境提升:`agentrum export`(Secret 值强制剥离)→ 目标环境 `agentrum apply`
- ✅ `agentrum init` 脚手架(agent/mcp-server/skill/prompt 四模板)
- ⏳ 试点验收清单(2-3 团队 × 4-6 周:发布→订阅→通知→部署闭环)——组织动作,待启动
- 可选池(未排期):Weblate、Meilisearch、订阅版本锁定(pin @tag)、团队配额、回收站、A2A Agent Card

## 已知取舍(诚实记录)

- 登录限流为进程内存版:多副本时各自计数,仍是有效缓解;严格全局限流需 Redis(阶段 B)
- JWT 会话在改密码后到过期前仍有效(MVP 无 jti 撤销表);API token 撤销是即时的
- 分页为 offset 制,数据量 >10 万行时升级游标制
