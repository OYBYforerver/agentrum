# Agentrum

**多租户的企业级 AI 资产注册中心** — 发布 · 订阅 · 部署 Agent、MCP Server、Skill 与 Prompt。

- 每个项目组拥有独立的命名空间,组内角色分明(admin / publisher / member)
- 跨团队订阅:`internal` 资源全公司可见,`restricted` 资源需属主团队审批
- 版本不可变:tag 一经发布永不移动,每次发布携带变更说明
- 原生 Kubernetes 部署控制器:镜像白名单管控,发布即代码执行的最后防线
- Secret 信封加密;SSO 走标准 OIDC(内置飞书预设)
- UI / 文档 / README 中英双语

本项目基于开源项目 [agentregistry](https://github.com/agentregistry-dev/agentregistry) 的架构思想全新实现,致敬原项目。详见仓库 [README](https://github.com/agentrum/agentrum)。
