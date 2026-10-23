# CLI 参考

`agentrum` CLI 是开发者与 CI 的主要入口。安装:`pip install agentrum`(或源码内 `uv sync` 后 `uv run agentrum`)。

## 两种登录方式

| 方式 | 适用 | 命令 | 凭据形态 |
|---|---|---|---|
| 账号登录 | 人(控制台同等权限) | `agentrum login --server URL --username U`(密码交互输入) | JWT,8 小时有效 |
| AK/SK 登录 | CI / 脚本 / 运行时 | `agentrum login --server URL --ak ARK-ak-xxx --sk ARK-sk-xxx` | HTTP Basic,受项目 scopes 约束 |

凭据保存在 `~/.agentrum/credentials.json`(权限 0600);CI 中推荐直接用环境变量 `AGENTRUM_SERVER` / `AGENTRUM_TOKEN` 或 `AGENTRUM_AK` / `AGENTRUM_SK`,无需落盘。

!!! note "权限差异"
    AK/SK 是**项目级**凭据:只能读写该项目命名空间、且受创建时勾选的 `read / publish / deploy` scopes 限制;管理操作(建项目、成员管理)必须用账号登录。

## 命令一览

```bash
agentrum login        # 登录(账号或 AK/SK)
agentrum apply FILE   # 发布 YAML 清单(-- 分隔多文档,kubectl 风格)
agentrum get KIND     # 列表;agentrum get KIND NAME -n NS 查看单个(输出 JSON)
agentrum delete KIND ns/name   # 软删除(重新 apply 同名资源即恢复)
agentrum init KIND NAME        # 脚手架:agent | mcp-server | skill | prompt
agentrum export -o bundle.yaml # 导出资源(含全部版本)用于跨环境提升
agentrum version      # 服务端版本
```

## 典型流程

```bash
# 1. 脚手架并发布一个 MCP Server
agentrum init mcp-server payment-gateway && cd payment-gateway
#    编辑 agentrum.yaml(见《资源规范》),然后:
agentrum apply agentrum.yaml

# 2. 查看发布结果
agentrum get MCPServer -n payment

# 3. 跨环境提升:指向生产注册中心重放同一份内容
agentrum export -o bundle.yaml -n payment
ARK_SERVER=https://registry.prod.internal ARK_AK=... ARK_SK=... agentrum apply bundle.yaml
```

!!! warning "导出不包含 Secret 值"
    `agentrum export` 对 Secret 资源只导出键名,值强制剥离——需在目标环境重新录入。
