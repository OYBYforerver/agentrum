# API 参考

交互式 OpenAPI 文档由服务自动提供:`/docs`(Swagger UI)与 `/openapi.json`。本页是按场景组织的接入要点。

## 认证

所有 `/v1/*` 接口都需要认证,支持两种形态:

```bash
# 1) 账号 JWT:POST /v1/auth/login 换取 token
curl -s $SERVER/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}'
# 后续请求:Authorization: Bearer <token>

# 2) 项目 AK/SK:HTTP Basic(推荐用于 CI / 运行时)
curl -s -u "$ARK_AK:$ARK_SK" $SERVER/v1/resources
```

规则速记:

- AK/SK 只能触达所属项目的命名空间,且受 `read / publish / deploy` scopes 限制
- Prompt 资源是**项目私有**,任何跨项目主体(含 AK)都读不到
- 登录连续失败 5 次触发锁定(10 分钟);请求体上限默认 2 MiB

## 核心端点(按场景)

| 场景 | 端点 | 说明 |
|---|---|---|
| 发布 / 更新 | `PUT /v1/resources/{kind}/{namespace}/{name}` | 幂等;创建返回 201,更新返回 200;tag 冲突 409 |
| 查询列表 | `GET /v1/resources?kind=&namespace=&q=&limit=&offset=` | `q` 为名称/描述子串搜索(pg_trgm 加速) |
| 查询单个 | `GET /v1/resources/{kind}/{ns}/{name}?tag=&version=` | 缺省返回最新版本 |
| 版本历史 | `GET /v1/resources/{kind}/{ns}/{name}/versions` | 含 `change_notes` |
| 软删除 | `DELETE /v1/resources/{kind}/{ns}/{name}` | 触发订阅方删除通知 |
| 项目 | `POST/GET /v1/teams`、`/v1/teams/{name}/members` | 建项目需平台管理员 |
| AK/SK | `POST/GET/DELETE /v1/teams/{name}/access-keys` | SK 仅创建响应中出现一次 |
| 订阅 | `POST /v1/teams/{team}/subscriptions` | 见《订阅与通知》 |
| 审计 | `GET /v1/audit` | 平台管理员 |
| 健康检查 | `GET /health`(存活)、`GET /readyz`(就绪,含 DB) | 探针用 |

## 响应与错误约定

```json
// 成功(资源对象)
{"kind": "MCPServer", "namespace": "payment", "name": "payment-gateway",
 "visibility": "internal", "catalog": {}, "status": {},
 "latest_version": {"version": 3, "tag": "v1.3.0", "spec": {...},
                    "change_notes": "...", "published_by": "alice"}}

// 失败
{"detail": "tag 'v1.2.0' already exists; tags are immutable"}
```

| 状态码 | 含义 |
|---|---|
| 400 | 校验失败(spec 不符合该 kind 契约、参数非法) |
| 401 | 未认证 / 凭据失效 |
| 403 | 无权限(角色不足、scope 缺失、私有/受限资源) |
| 404 | 资源不存在 |
| 409 | 冲突(tag 不可变、重复订阅、并发修改) |
| 413 | 请求体超限 |
| 429 | 登录限流 / 账号锁定 |

排查线索:每个响应都带 `X-Request-ID` 响应头,与结构化日志(需 `ARK_LOG_FORMAT=json`)中的 `request_id` 对应。

## 分页

`GET /v1/resources` 使用 `limit`(默认 50,上限 200)+ `offset`,响应含 `total`。当前为 offset 分页,数据量 >10 万行时计划升级游标制(见路线图)。
