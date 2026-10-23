# 研究报告:Agent/MCPServer/Skill/Prompt 的"新增"是否足够完善

> 结论先行:**当前的创建流程"可用但不完善"**。发布一个资源并打版本没有问题,但相比上游 agentregistry,我们缺了三类东西:**目录元数据**(决定注册中心作为"商店橱窗"的价值)、**运行要素**(env/凭据引用/git 源,决定部署控制器能否落地)、**开发者体验脚手架**(init/build,决定开发者愿不愿意来)。差距按 P0/P1/P2 分列于文末。

## 1. 现状(Agentrum,2026-10)

创建入口只有一个:`PUT /v1/resources/{kind}/{namespace}/{name}`(或 `agentrum apply` YAML),spec 为 JSON,按 kind 做最小校验:

| kind | 必填约束 | 附加字段 |
|---|---|---|
| Agent | `image` | 任意 extra |
| MCPServer | `transport` + (`endpoint` 或 `command`) | 任意 extra |
| Skill | 无硬约束 | 任意 extra |
| Prompt | `template` | 任意 extra |

资源级元数据:`labels`、`description`、`tag`(不可变)、`visibility`、软删除。没有图标/分类/文档链接/作者/许可证/示例,没有版本 changelog,没有凭据引用,没有 git 来源。

## 2. 上游对标(基于对 agentregistry 代码的核查)

上游为每类资源沉淀了更完整的模型与配套工作流:

- **Agent**:spec 携带完整部署载荷(image、env、tolerations、affinity、serviceAccount,BYO deployment);旧字段 `modelProvider/modelName` 以 deprecated 形式保留兼容;配合 `arctl init` 的框架脚手架和 `arctl build` 的 Docker 构建链
- **MCPServer**:部署为 kagent ToolServer,端点以 condition 形式回写(`http://<name>.<ns>.svc.cluster.local:3000/mcp`),支持 env;K8s 部署后的健康状态可查询
- **Skill**:核心是 **git 来源**——专用 controller 自动 pin/fetch git ref,支持私有仓库凭据;即"技能的正文在 git,注册中心存指针+版本"
- **Prompt**:模板型资源
- **额外 kind**:Runtime、Model、Plugin(git 来源 + controller)、Deployment、Secret(元数据与加密载荷分表)
- **开发者工作流**:`init` 脚手架 → 本地编辑 → `build --push` → `apply` → 部署 → `wait`;`configure` 一键把注册中心写入 vscode/cursor/claude-code/kiro 的 MCP 客户端配置

## 3. 差距清单(逐类)

| 维度 | Agent | MCPServer | Skill | Prompt |
|---|---|---|---|---|
| 凭据引用(env/secretRef) | ❌ | ❌ | — | — |
| 完整部署要素(资源限制/亲和/SA) | ❌ | 部分 | — | — |
| git 来源 + 服务端拉取 | ❌ | — | ❌(最大缺口) | — |
| 模板变量声明 | — | — | — | ❌ |
| 端点健康回写 | ❌ | ❌ | — | — |
| changelog(每版本说明) | ❌ | ❌ | ❌ | ❌ |
| 目录元数据(icon/分类/docs/作者/license/长描述/示例) | ❌×全部 | | | |
| 脚手架 init / 构建 build | ❌(上游有) | | | |

## 4. 为什么这很重要

1. **目录元数据贫瘠**会让 UI 变成"裸列表"——注册中心的信任与发现价值(上游 README 的核心卖点)有一半靠这些字段
2. **凭据引用与部署要素**是阶段 B 部署控制器的硬前置:没有 `env.secretRef` 模式,Agent 带着明文凭据入库,既不安全也部署不了
3. **Skill 的 git 源**是上游 Skill 的灵魂:没有它,Skill 只是"一段 JSON",无法跟踪上游仓库更新
4. **Prompt 变量声明**决定 Prompt 能否被 UI 表单化、被 MCP `get_prompts` 规范化消费

## 5. 分期建议

**P0(建议并入阶段 B 首批,部署控制器的前置)**
- 资源元数据扩展:`icon`、`category[]`、`docs_url`、`license`、`authors`、`long_description`(markdown)、`examples[]` —— 纯 schema 变更,工作量小收益大
- `env[].valueFrom.secretRef` 引用模式 + Secret kind(与阶段 B Secret 管理合并设计)
- `resource_versions` 增加 `change_notes`(每版本说明,通知文案直接带上)

**P1(阶段 B 中后期)**
- Skill git 源:`spec.source.git{url, ref, credentials_ref}` + asyncio 拉取/pin controller
- Prompt 变量声明:`spec.variables[{name, required, description}]`,供 UI 表单与 MCP 工具消费
- MCPServer 健康探测回写(已在阶段 B 清单)

**P2(开源前后的竞争力项)**
- `agentrum init <kind>` 脚手架 + `agentrum build` 构建链(对标上游,决定开发者口碑)
- 目录"官方认证"标签(运营治理配套)

## 6. 待决策点(需要产品判断)

1. 目录元数据字段集是否认可 P0 清单?(字段一旦有用户数据,变更成本高)
2. `init/build` 重型 DX 是否投入?(不投入则 CLI 保持"纯客户端",开发者自己写 Dockerfile)
3. Skill 是否照抄上游"git 为正文"的模式,还是允许"正文直接入库"两种来源并存?——建议并存,git 模式作为推荐
