# 订阅与通知

## 订阅流程

```
订阅方项目成员                          属主项目管理员
     │ POST /v1/teams/{team}/subscriptions
     │ {kind, namespace, name | "*"}
     ├─ 目标 internal ──► 立即 active ──► 可读,且收到后续版本通知
     └─ 目标 restricted ─► pending_approval ─► 属主 admin 审批
                                               ├─ 批准 → active(可读)
                                               └─ 拒绝 → revoked
```

- `name` 传 `*` 表示订阅整个命名空间(该空间内此类新资源发布都会通知)
- 订阅自身项目会得到 409;订阅 Prompt 得到 400(项目私有)
- 资源被删除时,所有 active 订阅方会收到 `resource.deleted` 通知

## 通知投递(事务性 outbox)

通知与引发它的状态变更**同事务落库**,后台投递器按间隔轮询投递,失败按指数退避重试(最多 5 次后标记 failed),`GET /v1/notifications` 可观测(平台管理员)。

### 渠道 1:飞书群机器人(推荐起步)

飞书群 → 设置 → 群机器人 → 添加自定义机器人,拿到 webhook URL:

```bash
ARK_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
ARK_FEISHU_WEBHOOK_SECRET=...   # 可选,开启签名校验
```

### 渠道 2:通用 Webhook(HMAC 签名)

```bash
ARK_NOTIFICATION_WEBHOOK_URL=https://your-service/hook
ARK_NOTIFICATION_WEBHOOK_SECRET=...
```

投递为 `POST`,JSON body 即事件负载;配置了 secret 时附带 `X-Agentrum-Signature: sha256_hex(payload)` 请求头供校验。

```json
{
  "event": "resource.published",
  "kind": "MCPServer",
  "namespace": "payment",
  "name": "payment-gateway",
  "version": 3,
  "tag": "v1.3.0",
  "subscriber_team": "support",
  "published_by": "alice",
  "description": "支付网关 MCP"
}
```

`event` 取值:`resource.published` / `resource.deleted`。

## 消费方图谱(属主视角)

```bash
curl -s -H "Authorization: Bearer $TOKEN" $SERVER/v1/teams/payment/consumers
# → [{"subscriber_team": "support", "kind": "MCPServer",
#     "namespace": "payment", "name": "payment-gateway", "since": "..."}]
```

下线或废弃资源前,先查这张图谱评估影响面。
