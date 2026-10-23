# Architecture

```
ui (Next.js static, i18n zh/en)
      │ REST
┌─────▼──────────────────────────────┐
│ FastAPI (routers = transport only) │
│   ├─ auth/oidc  (JWT + SSO)        │
│   ├─ resources (apply/get/delete)  │
│   ├─ subscriptions (approval)      │
│   └─ notifications (outbox)        │
├────────────────────────────────────┤
│ services (business logic)          │
│   ├─ tenancy / visibility          │
│   ├─ deployments.reconciler ───────┼──► K8s (kubernetes-asyncio)
│   ├─ probe / maintenance loops     │
│   └─ secrets (Fernet envelope)     │
├────────────────────────────────────┤
│ SQLAlchemy models (only DB layer)  │
└─────┬──────────────────────────────┘
      ▼
  PostgreSQL (JSONB specs, trigram search, outbox, audit)
```

Key properties:

- **Control plane, not data plane** — deployed workloads run independently; consumers should tolerate registry downtime (cache resolutions).
- **Transactional outbox** — notifications commit atomically with the state that caused them; a background dispatcher delivers with retries.
- **Level-triggered reconciliation** — Deployment rows declare desired state; the controller converges it, writing status conditions back.
