# Agentrum 路线图(定稿)

> 状态(2026-10-25):**阶段 A/B/C 主体全部落地**,版本 0.0.1(首次公开发布)。**0.1.0 五个工作流(W1-W5)开发完成**,待:推送触发 kind e2e 首跑、飞书预设真实应用验证、试点启动。
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

## 阶段 D — v0.1.0 完善可用 + 安全(开发中)

> 主题:**第一个完善可用、且没有已知安全问题的平台**。合并原"消费闭环"与"试点硬化"两版为单一 0.1.0,五个工作流并行推进。
>
> 安全基线(2026-10-25 代码级扫描):Argon2 + 防枚举、SK 哈希存储、改密码即撤销会话(password_changed_at + iat)、禁用用户后 JWT/API token/AK-SK 全部即时失效(REST 与 MCP 两路径均检查 disabled_at)——**均已在代码中实现,原"已知取舍"记录过时,已更正**;真实缺口:①会话撤销行为无 API 级回归测试保护;②服务端出站请求无 egress 防护(git ls-remote / 健康探测可指向内网与云元数据地址,SSRF 面);③Skill 内容交付需内建路径穿越防护。

### W1 安全硬化
| 项 | 内容 | 状态 |
|---|---|---|
| 会话撤销回归测试 | API 级测试锁定:改密码/重置/禁用后,旧 JWT(REST + MCP 路径)、API token、AK/SK 即时失效 | ✅ |
| 限流可插拔后端 | 登录限流/失败锁定支持 Redis(配置即全局),默认仍内存 | ✅ |
| Egress 防护 | git 拉取/健康探测/内容交付统一出站守卫:scheme 白名单(https/http/git),默认拒绝 loopback + link-local(云元数据),私网段可配置;探测不跟随重定向 | ✅ |

### W2 消费闭环
| 项 | 内容 | 状态 |
|---|---|---|
| Skill 内容交付 API | `GET /v1/resources/Skill/{ns}/{name}/content`:服务端凭注册中心凭据在锁定 SHA 拉取,tarball 交付给已授权订阅方;凭据不出库;subdirectory 路径穿越防护 | ⏳ |
| Agent 端点交付 | AgentSpec 可选 `endpoint`(外部托管);调和器回写集群内 Service URL condition;`protocol: openapi` 增 `openapi_url` | ⏳ |
| Python 消费 SDK | `agentrum.resolve()` 统一入口:MCPServer→连接配置、Skill→内容、Prompt→模板+本地渲染;AK/SK 认证;缓存 + 宕机兜底 | ⏳ |
| Prompt 进 MCP 工具面 | `/mcp` 暴露标准 prompts capability(含变量 schema) | ⏳ |
| `agentrum configure` | 一键写入 Cursor / Claude Code 等 MCP 客户端配置 | ⏳ |

### W3 验证(可信)
| 项 | 内容 | 状态 |
|---|---|---|
| K8s 控制器 kind e2e | CI 作业(push 触发):kind 集群 + 镜像加载 + Helm 安装 + 发布 Deployment 资源 → Ready condition(含 service_url)→ kubectl 验证工作负载;白名单外镜像禁止落地 | ✅(待推送首跑) |
| OIDC 实测 | CI 起 Dex 真实握手(登录/审批/code 交换/JIT 建号/二次登录不重复/state 防伪);**实测发现并修复生产 bug:generic authorize URL 构造 KeyError,此前任何真实 IdP 登录必崩**;飞书预设仍待真实企业应用验证 | ✅(generic)/⏳(飞书) |

### W4 功能补全
| 项 | 内容 | 状态 |
|---|---|---|
| 订阅版本锁定 | subscription `pinned_tag`(建订阅时指定或 PATCH 修改/解除);被 pin 的订阅方在新版本发布时收到明确"新版本可用,你锁定在 X,无需行动"提示 | ✅ |
| 回收站 | 重新 apply 同名资源即恢复(已有);新增保留期清理(`ARK_RESOURCE_RETENTION_DAYS`,默认 30 天,版本与 Secret 载荷级联硬删);墓碑列表(include_deleted)已有 | ✅ |
| 审计日志 UI | 控制台新增审计页(平台管理员可见):分页表格(时间/操作人/动作/对象/详情/来源 IP),中英双语 | ✅ |
| UI v0.1 | 新页面(审计)自带错误/空/加载态;订阅列表显示 pin 徽章;整体打磨按计划依试点反馈推进 | 🔶(依试点) |

### W5 文档
| 项 | 内容 | 状态 |
|---|---|---|
| 消费方指南 | 每类资源一节;`uvx agentrum` 一等安装方式 | ⏳ |

可选池(未排期):MCP Registry server.json 兼容导出、A2A Agent Card 深化、游标分页、Meilisearch、Weblate、团队配额、SCIM、SMTP 通知、`agentrum build`(待控制器真集群验证后)。

## 已知取舍(诚实记录)

- 登录限流为进程内存版:多副本时各自计数,仍是有效缓解;严格全局限流需 Redis(0.1.0 W1 解决)
- 会话撤销:改密码/重置即时失效(password_changed_at + iat);禁用用户后 JWT(403)/API token/AK-SK 亦即时失效——~~原记录"改密码后仍有效至过期"有误,2026-10-25 更正~~,遗留问题是无 API 级回归测试保护(0.1.0 W1)
- 分页为 offset 制,数据量 >10 万行时升级游标制
