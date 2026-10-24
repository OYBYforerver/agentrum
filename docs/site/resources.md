# 资源规范(agentrum.yaml)

所有资源共用一个信封:`kind + metadata + spec`,通过 `agentrum apply` 或 `PUT /v1/resources/...` 提交。`spec` 允许多余字段(向前兼容),但必须满足各 kind 的最小契约;每次发布会在 spec 里落一个 `spec_version` 戳,形状演进时用它区分新旧版本。

编辑器补全:把 `$schema: http://<server>/v1/schema/manifest.json` 写进 agentrum.yaml(公开端点,无需凭据),yaml-language-server 即可校验/自动补全;`agentrum init` 生成的模板已带此键。

```yaml
kind: MCPServer
$schema: http://localhost:12122/v1/schema/manifest.json
metadata:
  name: payment-gateway        # 小写字母/数字/-,全局唯一(kind+namespace+name)
  namespace: payment           # 所属项目命名空间
  labels: {team: payment}
spec:                          # 各 kind 的负载,见下表
  transport: streamable-http
  endpoint: http://pg.payment:3000/mcp
tag: v1.2.0                    # 不可变:重复发布同名 tag 返回 409
change_notes: 本次变更说明      # 随订阅通知发送
description: 支付网关 MCP
visibility: internal           # internal | restricted(prompt 强制 private)
catalog:                       # 目录元数据(可变,不产生新版本)
  title: 支付网关
  long_description: "支持 Markdown 的详细介绍…"
  keywords: [payment, mcp]
  authors: [alice]
  license: Apache-2.0
  links: {docs: "https://...", source: "https://..."}
```

## 各 kind 的 spec 契约

| kind | 必填 | 常用可选 | 说明 |
|---|---|---|---|
| `Agent` | `image` | `framework`、`protocol`(`mcp/a2a/openapi/http/custom`)、`agent_card_url`(A2A 卡片,protocol=a2a 时必填)、`capabilities[]`、`env[]` | env 项:`{name, value}` 或 `{name, value_from: {secret_ref: {name, key}}}`;集群放置(namespace/replicas)归 Deployment 管 |
| `MCPServer` | `transport` +(`endpoint` 或 `command`) | `args[]`(仅 stdio,如 `npx -y @mcp/xxx` 的参数)、`headers[]`(远程鉴权头,同 env 项格式,值可引用 Secret)、`env[]` | transport ∈ `streamable-http / sse / stdio`;http 类必须给 endpoint,stdio 必须给 command 且不允许 args |
| `Skill` | `source.git.url` 或 `instructions`(二选一) | `entrypoint`、`source.git.ref/subdirectory/credentials_ref` | git 来源见下节 |
| `Prompt` | `template` | `variables[]`(`{name, required, description}`) | **仅本项目可见**;模板里的 `{{占位符}}` 与 `variables` 必须一一对应,多声明/少声明都拒绝发布 |
| `Secret` | `data`(键值对象) | — | 值信封加密,永不回显;强制 `restricted` |
| `Deployment` | `target_kind/target_namespace/target_name` | `tag`(锁定版本)、`cluster_namespace`、`replicas`、`port`、`image_pull_policy` | 见《部署接入》 |

## 环境变量与 Secret 引用示例

```yaml
kind: Agent
metadata: {name: fraud-detection, namespace: payment}
spec:
  image: registry.internal/fraud:1.0
  env:
    - {name: LOG_LEVEL, value: info}
    - name: API_KEY
      value_from:
        secret_ref: {name: api-keys, key: API_KEY}   # 引用同项目 Secret
```

## 可见性模型

| visibility | 谁能读 | 跨项目订阅 |
|---|---|---|
| `internal` | 全部登录用户 | 直接生效 |
| `restricted` | 属主项目 + 已订阅项目 | 需属主项目 admin 审批 |
| `private`(仅 Prompt) | 仅属主项目成员 | 不允许 |

发布需要属主命名空间的 `publisher`/`admin` 角色,或具备 `publish` scope 的项目 AK/SK。版本号单调递增,tag 不可变;软删除后重新发布即恢复。

## Skill 的 git 来源

技能正文推荐放在 git,注册中心存“指针 + 锁定的 commit SHA”:

```yaml
kind: Skill
metadata: {name: gateway-skill, namespace: payment}
spec:
  source:
    git:
      url: https://git.internal/pay/skills.git
      ref: main                      # 分支 / tag / 完整 commit SHA
      subdirectory: skills/gateway   # 可选:仓库内子目录
      credentials_ref: git-creds     # 可选:私有仓库凭据(Secret,含 username/password 或 token)
  entrypoint: SKILL.md               # 可选:仓库内入口文件
```

发布时服务端把 `ref` **解析为 commit SHA 并锁定进不可变版本**——即使 `ref` 写的是分支,版本记录的也是发布那一刻的位置;解析失败(仓库不可达、ref 不存在、凭据无效)会直接阻断发布。后台漂移检测(`ARK_SKILL_DRIFT_INTERVAL_SECONDS`,默认 300s,0 关闭)发现上游移动时在资源状态标记 `UpstreamDrift`,**不会自动改版本**——重新发布即追平。SSH 协议暂不支持,HTTPS + 令牌凭据即可覆盖内部 GitLab/GitHub。

发布时还会把入口文件(默认 `SKILL.md`)**内容快照进版本 spec**(`entrypoint_snapshot`:路径、正文、解析出的 frontmatter),上游仓库消失后已发布版本依然自包含。若 SKILL.md 带标准 frontmatter:`name` 必须与资源名一致、`description` 必填(Anthropic skill 格式),不一致直接拒绝发布。

## MCP Server 连接片段

目录条目 → 可用配置,一步完成:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://<server>/v1/resources/MCPServer/payment/payment-gateway/connect
```

返回 `transport`、stdio 启动方式(`command/args/env`)或远程 `url/headers`,以及三种即贴即用的客户端配置:`clients.claude_code`(可直接执行的 `claude mcp add ...`)、`clients.cursor`、`clients.generic`(标准 `mcpServers` JSON)。引用了 Secret 的 env/header **不会**出现在片段里,而是进入 `notes` 提示用户在客户端侧自行配置——注册中心的密钥永远不出服务端。MCP 通道(`get_resource` 工具)的返回里同样带 `connect` 块,IDE 内直接可取。

## 弃用(Deprecation)

资源下线不只有软删除一条路:先**弃用**——资源保持可见可读,订阅方收到 `resource.deprecated` 通知,目录与 MCP 列表带弃用标记:

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -d '{"deprecated": true, "deprecation_reason": "superseded", "successor": "payment/payment-gateway-v2"}' \
  https://<server>/v1/resources/Agent/payment/payment-gateway
```

`successor` 指向替代资源(可选),`deprecated: false` 可撤销弃用。弃用通知发送给全部 active 订阅方(不受订阅 `events` 偏好限制——这是针对既有消费方的 impact warning)。控制台详情页会显示弃用横幅。
