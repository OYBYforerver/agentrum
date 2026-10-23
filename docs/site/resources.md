# 资源规范(agentrum.yaml)

所有资源共用一个信封:`kind + metadata + spec`,通过 `agentrum apply` 或 `PUT /v1/resources/...` 提交。`spec` 允许多余字段(向前兼容),但必须满足各 kind 的最小契约。

```yaml
kind: MCPServer
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
| `Agent` | `image` | `framework`、`env[]` | env 项:`{name, value}` 或 `{name, value_from: {secret_ref: {name, key, namespace?}}}` |
| `MCPServer` | `transport` +(`endpoint` 或 `command`) | `env[]` | transport ∈ `streamable-http / sse / stdio`;http 类必须给 endpoint,stdio 必须给 command |
| `Skill` | — | `entrypoint`、`instructions` | git 来源模式(`source.git`)规划中 |
| `Prompt` | `template` | 变量声明规划中 | **仅本项目可见**;跨项目订阅直接拒绝 |
| `Secret` | `data`(键值对象) | — | 值信封加密,永不回显;默认 `restricted` |
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
