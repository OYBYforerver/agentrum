# API Reference

Interactive OpenAPI is served by the app itself: `/docs` (Swagger UI) and `/openapi.json`. This page organizes the integration essentials by scenario.

## Authentication

Every `/v1/*` endpoint requires auth, in one of two forms:

```bash
# 1) Account JWT: exchange credentials via POST /v1/auth/login
curl -s $SERVER/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}'
# Then: Authorization: Bearer <token>

# 2) Project AK/SK: HTTP Basic (recommended for CI / runtime)
curl -s -u "$ARK_AK:$ARK_SK" $SERVER/v1/resources
```

Quick rules:

- AK/SK can only reach their own project's namespace, within the `read / publish / deploy` scopes granted at creation
- Prompts are **project-private** — no cross-project principal (AK included) can read them
- 5 consecutive failed logins trigger a 10-minute lockout; request bodies are capped at 2 MiB by default

## Core endpoints (by scenario)

| Scenario | Endpoint | Notes |
|---|---|---|
| Publish / update | `PUT /v1/resources/{kind}/{namespace}/{name}` | Idempotent; 201 create, 200 update; tag conflict → 409 |
| List | `GET /v1/resources?kind=&namespace=&q=&limit=&offset=` | `q` = substring search over name/description (pg_trgm) |
| Get one | `GET /v1/resources/{kind}/{ns}/{name}?tag=&version=` | latest version by default |
| Version history | `GET /v1/resources/{kind}/{ns}/{name}/versions` | includes `change_notes` |
| Soft delete | `DELETE /v1/resources/{kind}/{ns}/{name}` | fires deletion notifications to subscribers |
| Projects | `POST/GET /v1/teams`, `/v1/teams/{name}/members` | creating projects requires platform admin |
| AK/SK | `POST/GET/DELETE /v1/teams/{name}/access-keys` | SK appears exactly once, in the create response |
| Subscriptions | `POST /v1/teams/{team}/subscriptions` | see Subscribe & notifications |
| Audit | `GET /v1/audit` | platform admin |
| Health | `GET /health` (liveness), `GET /readyz` (readiness incl. DB) | for probes |

## Response & error conventions

```json
// Success (resource object)
{"kind": "MCPServer", "namespace": "payment", "name": "payment-gateway",
 "visibility": "internal", "catalog": {}, "status": {},
 "latest_version": {"version": 3, "tag": "v1.3.0", "spec": {...},
                    "change_notes": "...", "published_by": "alice"}}

// Failure
{"detail": "tag 'v1.2.0' already exists; tags are immutable"}
```

| Status | Meaning |
|---|---|
| 400 | Validation failed (spec violates the kind contract, bad params) |
| 401 | Unauthenticated / expired credentials |
| 403 | Forbidden (insufficient role, missing scope, private/restricted resource) |
| 404 | Not found |
| 409 | Conflict (immutable tag, duplicate subscription, concurrent write) |
| 413 | Body too large |
| 429 | Rate limited / account locked |

Troubleshooting: every response carries an `X-Request-ID` header that matches `request_id` in structured logs (enable `ARK_LOG_FORMAT=json`).

## Pagination

`GET /v1/resources` uses `limit` (default 50, max 200) + `offset`; responses include `total`. Offset pagination today; cursor pagination is planned for very large catalogs (see roadmap).
