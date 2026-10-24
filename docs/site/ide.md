# IDE 接入(MCP)

Agentrum 注册中心自身就是一个 MCP Server——Cursor、Claude Code、Cline 等 MCP 客户端可以直接"问"注册中心:有哪些可用的 MCP 服务/Agent,端点是什么,最新版本到哪了。只读工具面,权限与控制台完全一致(JWT 或项目 AK/SK)。

## 端点与认证

```
Streamable HTTP:  http://<registry-host>:12122/mcp
认证:             Authorization: Bearer <JWT>   或   Authorization: Basic <AK>:<SK>(base64)
```

建议给 IDE 配一把只读(`read` scope)的项目 AK/SK:控制台 → 项目 → 设置 → AK/SK 凭据。

## Cursor / Claude Code 配置

```json
{
  "mcpServers": {
    "agentrum": {
      "url": "http://localhost:12122/mcp",
      "headers": {
        "Authorization": "Basic <base64(AK:SK)>"
      }
    }
  }
}
```

## 暴露的工具

| 工具 | 说明 |
|---|---|
| `registry_overview` | 各 kind 可见资源数量 + 服务版本 |
| `list_resources` | 按类型/命名空间/关键字列目录(可见性过滤后) |
| `get_resource` | 取单个资源详情:最新(或指定 tag)的 spec、端点、change_notes、目录元数据 |

典型用法:在 IDE 里问"注册中心里有哪些支付相关的 MCP 服务?"——客户端调用 `list_resources(search=支付)`,再 `get_resource` 拿到端点与版本,直接接入配置。

!!! note "可见性即权限"
    工具返回内容与调用主体在控制台里能看到的一致:AK/SK 只见所属项目与已订阅内容,internal 资源全公司可见,Prompt 项目私有不可见。
