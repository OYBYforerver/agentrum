# Subscribe & notifications

## Subscription flow

```
Subscriber project member                  Owner project admin
     │ POST /v1/teams/{team}/subscriptions
     │ {kind, namespace, name | "*"}
     ├─ target internal ──► active at once ──► readable + notified on versions
     └─ target restricted ► pending_approval ─► owner admin decides
                                               ├─ approve → active (readable)
                                               └─ reject  → revoked
```

- `name: "*"` subscribes to the whole namespace (notified for every new release of that kind)
- Subscribing to your own project → 409; subscribing to a Prompt → 400 (project-private)
- When a resource is deleted, every active subscriber receives a `resource.deleted` notification

## Delivery (transactional outbox)

Notifications commit **in the same transaction** as the state change that caused them; a background dispatcher polls and delivers, retrying with exponential backoff (max 5 attempts, then `failed`). `GET /v1/notifications` (platform admin) exposes the pipeline.

### Channel 1: Feishu custom bot (recommended to start)

Feishu group → Settings → Bots → add a custom bot, grab the webhook URL:

```bash
ARK_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
ARK_FEISHU_WEBHOOK_SECRET=...   # optional, enables signing
```

### Channel 2: Generic webhook (HMAC-signed)

```bash
ARK_NOTIFICATION_WEBHOOK_URL=https://your-service/hook
ARK_NOTIFICATION_WEBHOOK_SECRET=...
```

Delivery is a `POST` whose JSON body is the event payload; with a secret configured, a `X-Agentrum-Signature: sha256_hex(payload)` header is attached.

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
  "description": "Payment gateway MCP"
}
```

`event` values: `resource.published` / `resource.deleted`.

## Consumer graph (owner view)

```bash
curl -s -H "Authorization: Bearer $TOKEN" $SERVER/v1/teams/payment/consumers
# → [{"subscriber_team": "support", "kind": "MCPServer",
#     "namespace": "payment", "name": "payment-gateway", "since": "..."}]
```

Check this graph before deprecating or removing anything — it is your impact analysis.
