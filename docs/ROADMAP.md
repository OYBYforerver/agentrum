# Agentrum 路线图(定稿)

> 决策记录:通知渠道 = 飞书;资源发布即生效(无发布审批);UI = React/Next.js + react-i18next 双语;部署目标 = **K8s 集群**(原生适配器优先,Docker 仅作本地开发模式);身份 = **标准 OIDC 协议 + 飞书作为 Provider 配置**(开源通用,企业配飞书,社区配任意 OIDC IdP);本地账号保留为 bootstrap 兜底。

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

## 阶段 B — 集群生产

- 资源模型增强(P0,部署控制器前置):目录元数据(icon/category/docs/authors/license/long_description/examples)、`env[].valueFrom.secretRef` 引用模式、版本 `change_notes` —— 详见 [RESEARCH-resource-model.md](RESEARCH-resource-model.md)
- OIDC SSO(authlib,Provider 抽象;飞书 profile + 任意标准 OIDC)
- K8s 部署控制器:`kubernetes-asyncio` 原生 Deployment/Service 适配器;ServiceAccount 按目标命名空间最小授权;**镜像仓库白名单 + 摘要 pin**(发布权≈代码执行权,必须管控)
- Secret 资源类型 + 信封加密(cryptography,后续接 KMS)
- Helm Chart:双副本 + initContainer 跑迁移(避免多副本迁移竞态)+ Ingress
- 资源健康探测(MCPServer 端点存活 → conditions)
- 消费方图谱(GET /teams/{team}/consumers)+ 删除级联通知
- 双语 UI(react-i18next,上游组件设计可借鉴)
- pg_trgm 搜索;OTel metrics + tracing;pg_dump 定时备份;审计保留策略
- 消费端容错规范:缓存解析结果,容忍注册中心短时不可用(写入 README 运维章节)

## 阶段 C — 开源发布

- README.en / CONTRIBUTING / SECURITY.md / DCO / PR-模板
- mkdocs-material + mkdocs-static-i18n 双语文档站
- 发布流水线:ghcr 镜像 + cosign 签名 + semver
- 多环境提升(agentrum export / apply 跨环境包)
- 试点验收清单(2-3 团队跑 4-6 周:发布→订阅→通知→部署闭环)
- 可选池:Weblate(社区翻译)、Meilisearch(中文搜索升级)、订阅版本锁定(pin @tag)、团队配额、回收站、A2A Agent Card

## 已知取舍(诚实记录)

- 登录限流为进程内存版:多副本时各自计数,仍是有效缓解;严格全局限流需 Redis(阶段 B)
- JWT 会话在改密码后到过期前仍有效(MVP 无 jti 撤销表);API token 撤销是即时的
- 分页为 offset 制,数据量 >10 万行时升级游标制
