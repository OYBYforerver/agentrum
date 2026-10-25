# Python SDK(消费方)

应用程序在运行时消费注册中心资产的标准方式:`agentrum.sdk`。发现、取内容、渲染模板,一个入口;本地缓存让注册中心宕机不影响你的应用——这正是"控制面注册中心"的设计承诺。

## 安装与凭据

```bash
pip install agentrum          # 或无需安装:uvx agentrum …(CLI)
```

凭据解析顺序:显式参数 → `AGENTRUM_AK`/`AGENTRUM_SK`(或 `AGENTRUM_TOKEN`)环境变量 → `agentrum login` 存的本地凭据。推荐给应用配一把只读 scope 的项目 AK/SK(控制台 → 设置 → AK/SK)。

## resolve:四类资源一个入口

```python
import agentrum.sdk as agentrum

registry = agentrum.Registry("https://registry.internal", ak=..., sk=...)

# MCP Server:拿到端点与连接头,直接用任意 MCP 客户端连接
server = registry.resolve("MCPServer/payment/payment-gateway")
#   server.endpoint, server.transport, server.headers(仅字面值;
#   secretRef 引用的头不会出库,需与属主团队另行约定)

# Agent:外部托管的有 spec.endpoint,控制器部署的看 Ready condition
# 里的 service_url(status.conditions[0].service_url)

# Skill:锁定 SHA + 内容
skill = registry.resolve("Skill/team/pay-skill")   # skill.sha
registry.fetch_skill("Skill/team/pay-skill", dest="./skills")

# Prompt:模板 + 声明式变量,本地渲染(缺失必填/传入未声明 → 报错)
prompt = registry.resolve("Prompt/team/review-style")
text = prompt.render(language="python")
```

## 缓存与宕机兜底

`resolve()` 的结果按 TTL(默认 300s)落盘缓存(默认 `~/.agentrum/cache`,可用 `AGENTRUM_CACHE_DIR` 或 `cache_dir` 覆盖)。注册中心不可达时返回**过期的缓存副本**(`resolved.stale == True`);4xx(凭据失效、资源不存在)不兜底,直接抛错——那是真实问题,不该被旧数据掩盖。

## Skill 内容交付

```python
registry.fetch_skill("Skill/team/pay-skill", dest="./skills")
```

服务端用**注册中心持有的凭据**在锁定 SHA 上拉取并打包返回——私有仓库的订阅方拿得到内容,而凭据永不离开注册中心。解包使用 tarfile 的 `data` 过程滤器,成员路径逃逸会被拒绝。

等价的 REST 调用:`GET /v1/resources/Skill/{ns}/{name}/content?tag=…`(响应头 `X-Agentrum-Sha` 为锁定 commit)。

## MCP 工具面(IDE 内)

`/mcp` 除 `list_resources` / `get_resource` 外,还提供 Prompt 工具:

| 工具 | 说明 |
|---|---|
| `list_prompts` | 列出你能看到的 Prompt(Prompt 项目私有),含已声明变量 |
| `get_prompt` | 不带 `variables_json` 返回模板+变量;带则服务端渲染(必填/未声明强校验) |

IDE Agent 可以直接"取用注册中心治理过的提示词",管理动作(发布/版本/审批)仍只在控制台与 CLI。
