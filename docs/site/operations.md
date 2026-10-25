# 运维手册

## 环境变量参考

| 变量 | 默认 | 说明 |
|---|---|---|
| `ARK_DATABASE_URL` | `postgresql+asyncpg://agentrum:agentrum@localhost:5433/agentrum` | PostgreSQL 连接串(生产用外部 HA 实例) |
| `ARK_SECRET_KEY` | `dev-insecure-change-me` | JWT 密钥,**必改** |
| `ARK_SECRET_ENCRYPTION_KEY` | 由 SECRET_KEY 派生(会告警) | Secret 信封加密主键(Fernet,32 字节 urlsafe b64) |
| `ARK_ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | 会话有效期 |
| `ARK_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` | `admin` / `admin123` | 首启建号,**必改** |
| `ARK_ALLOWED_ORIGINS` | `*` | CORS 白名单(逗号分隔) |
| `ARK_LOG_FORMAT` | `console` | `json` 供日志平台采集 |
| `ARK_MAX_BODY_BYTES` | `2097152` | 请求体上限 |
| `ARK_IMAGE_ALLOWLIST` | 空(仅限开发) | 部署镜像白名单前缀,逗号分隔 |
| `ARK_FEISHU_WEBHOOK_URL/SECRET` | — | 飞书机器人通知 |
| `ARK_NOTIFICATION_WEBHOOK_URL/SECRET` | — | 通用 webhook(签名头 `X-Agentrum-Signature`) |
| `ARK_OIDC_GENERIC_ISSUER/CLIENT_ID/CLIENT_SECRET` | — | 通用 OIDC |
| `ARK_RATELIMIT_BACKEND` | `memory` | `redis` 时登录限流/失败锁定全局共享(需 `agentrum[redis]`;Redis 故障时 fail-open 并告警) |
| `ARK_RATELIMIT_REDIS_URL` | `redis://localhost:6379/0` | 限流后端地址 |
| `ARK_EGRESS_ALLOW_PRIVATE_ADDRESSES` | `true` | 服务端出站(git 拉取/健康探测/内容交付)是否可达私网段(内网 git 服务通常需要) |
| `ARK_EGRESS_ALLOW_LOOPBACK` | `false` | 开发用:放行 loopback/link-local(含云元数据段,默认拒绝) |
| `ARK_EGRESS_ALLOW_FILE_SOURCES` | `false` | 开发/测试用:放行 file:// git 源 |
| `ARK_SKILL_CONTENT_MAX_BYTES` | `52428800` | Skill 内容交付的 tarball 大小上限 |
| `ARK_RESOURCE_RETENTION_DAYS` | `30` | 软删除资源在回收站保留的天数,过期由保留期清理硬删(版本与 Secret 载荷级联) |
| `ARK_FEISHU_APP_ID/APP_SECRET` | — | 飞书 SSO |
| `ARK_OIDC_REDIRECT_BASE` / `ARK_UI_ORIGIN` | — | 回调基址 / UI 跳转地址 |
| `ARK_PROBE_INTERVAL_SECONDS` | `60` | MCPServer 端点探测周期 |
| `ARK_DEPLOY_INTERVAL_SECONDS` | `10` | 部署调和周期 |
| `ARK_AUDIT_RETENTION_DAYS` | `180` | 审计保留 |
| `ARK_NOTIFICATION_RETENTION_DAYS` | `30` | 已投递通知保留 |
| `ARK_OTEL_ENABLED` / `ARK_OTELENDPOINT` | `false` | OTLP 追踪(默认关) |

## Kubernetes 部署

```bash
helm upgrade --install agentrum charts/agentrum \
  --set database.url="postgresql+asyncpg://user:pass@db:5432/agentrum" \
  --set auth.secretKey="$(openssl rand -hex 32)" \
  --set auth.bootstrapAdminPassword="$(openssl rand -hex 16)" \
  --set secrets.encryptionKey="$(openssl rand -base64 32)" \
  --set deploy.imageAllowlist="registry.internal/" \
  --set ingress.enabled=true --set ingress.host=registry.internal
```

要点:双副本默认;**迁移在 initContainer 执行**,应用 Pod 不跑 alembic(避免多副本竞态);`/readyz` 就绪探针含 DB 检查;控制器 RBAC 命名空间最小授权。

## 备份与恢复

```bash
# 每日逻辑备份(配合 crontab / K8s CronJob)
kubectl exec deploy/postgres -- pg_dump -U agentrum agentrum | gzip > backup-$(date +%F).sql.gz
# 恢复
gunzip -c backup-2026-10-24.sql.gz | psql -U agentrum agentrum
```

Secret 值为信封加密密文——**备份必须与 `ARK_SECRET_ENCRYPTION_KEY` 一并保管**,丢 key = Secret 不可恢复。

## 可观测性

- `/metrics`:Prometheus 指标(HTTP 请求量/时延/状态码)
- `ARK_LOG_FORMAT=json`:结构化日志,含 `request_id`(与响应头 `X-Request-ID` 对应)
- `ARK_OTEL_ENABLED=true` + `ARK_OTEL_ENDPOINT`:OTLP 追踪
- 探活:`/health`(进程)、`/readyz`(DB 就绪)

## 消费端容错约定(重要)

注册中心是**控制面**而非数据面:已部署的 Agent/MCP Server 独立运行,不经过注册中心。消费端应缓存解析结果并对注册中心短时不可用做重试——**不要让运行时强依赖注册中心**,否则它的一次抖动会放大成全公司新发布停摆。
