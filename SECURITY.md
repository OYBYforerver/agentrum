# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately via GitHub
"Report a vulnerability" (Security tab) or email the maintainers listed in
the repo owner profile. **Do not open public issues for security reports.**

We aim to acknowledge within 3 business days and publish a fix with credit
(unless you prefer otherwise) after a patch release.

## Scope notes

- Agentrum is an internal-facing platform: run it behind TLS (the chart
  supports Ingress) and never expose it publicly without review.
- The deployment controller executes workloads in your cluster — keep
  `ARK_IMAGE_ALLOWLIST` set in production; an empty allowlist is a
  development-only posture.
- Secret values are encrypted at rest (Fernet envelope); set a dedicated
  `ARK_SECRET_ENCRYPTION_KEY`, not the derived default.
