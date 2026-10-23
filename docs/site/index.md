# Agentrum

**多租户的企业级 AI 资产注册中心** — 发布 · 订阅 · 部署 Agent、MCP Server、Skill 与 Prompt。

本项目基于开源项目 [agentregistry](https://github.com/agentregistry-dev/agentregistry) 的架构思想全新实现,致敬原项目(详见仓库 [README](https://github.com/agentrum/agentrum))。

## 按角色找文档

| 你是谁 | 从这里开始 |
|---|---|
| 想发布资源的开发者 | [快速开始](quickstart.md) → [CLI 参考](cli.md) → [资源规范](resources.md) |
| 写脚本 / CI / 运行时 | [API 参考](api.md)(AK/SK 认证、错误码、分页) |
| 项目管理员 | [订阅与通知](subscribe.md) → [SSO 接入](sso.md) |
| 平台 / SRE | [部署接入](deploy.md) → [运维手册](operations.md) |

## 三个核心概念

1. **项目(Project)**:资源的隔离单元,平台管理员开通,成员分 admin / publisher / member 三种角色
2. **AK/SK**:项目级机器凭据,注册、发现、调用必须携带;scopes 控制 read/publish/deploy
3. **订阅**:跨团队消费的授权 + 通知机制;`internal` 直接生效,`restricted` 需属主审批,Prompt 仅本项目私有

交互式 API 文档(OpenAPI)由服务直接提供:`/docs`。
