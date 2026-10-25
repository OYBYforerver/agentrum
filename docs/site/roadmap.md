# Roadmap

The living roadmap with decision records lives in the repository:

- [docs/ROADMAP.md](https://github.com/OYBYforerver/agentrum/blob/main/docs/ROADMAP.md) — phases, status and known trade-offs
- [docs/RESEARCH-resource-model.md](https://github.com/OYBYforerver/agentrum/blob/main/docs/RESEARCH-resource-model.md) — resource model completeness study vs upstream

Phases:

1. **Phase A — pilot-ready**: auth hardening, user governance, Feishu notifications, CLI, CI ✅
2. **Phase B — cluster production**: catalog metadata, Secrets, OIDC SSO, K8s deployment controller, Helm chart, bilingual UI, probes, search, observability ✅
3. **Phase C — open source**: bilingual docs (this site), release pipeline (ghcr + cosign), multi-env promotion (`agentrum export`), scaffolding (`agentrum init`) ✅
4. **Phase D — v0.1.0 complete & secure** (in development, five workstreams):
   - **W1 security**: JWT dies on user disable, pluggable Redis rate limiting, egress guard for server-initiated requests (scheme allowlist, loopback/link-local blocked)
   - **W2 consumption closure**: Skill content delivery API, Agent endpoint delivery (spec field + reconciler URL writeback + `openapi_url`), Python consumer SDK (`agentrum.resolve()`), Prompt via MCP prompts capability, `agentrum configure`
   - **W3 verification**: kind e2e for the deploy controller, OIDC code flow against Dex in CI
   - **W4 features**: subscription pin @tag, recycle bin, audit UI, UI polish
   - **W5 docs**: per-kind consumer guides, `uvx` as the first-class CLI install
