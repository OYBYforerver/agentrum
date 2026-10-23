# SSO setup (admins)

Agentrum's identity model: **humans** use JWT (SSO or account password), **machines** use project AK/SK. SSO is standard OIDC — any discovery-capable IdP works, and Feishu ships as a built-in preset. Local accounts remain for bootstrap.

## Generic OIDC (recommended)

For Keycloak / Casdoor / Authelia / Logto / Okta etc., register an OIDC application in your IdP (redirect URI: `$ARK_OIDC_REDIRECT_BASE/v1/auth/oidc/generic/callback`), then:

```bash
ARK_OIDC_GENERIC_ISSUER=https://sso.internal/realms/acme   # discovery is automatic
ARK_OIDC_GENERIC_CLIENT_ID=agentrum
ARK_OIDC_GENERIC_CLIENT_SECRET=...
ARK_OIDC_GENERIC_SCOPES="openid profile email"
ARK_OIDC_REDIRECT_BASE=https://registry.internal           # callback base
ARK_UI_ORIGIN=https://registry.internal                    # where browsers land after login
```

Verify with `GET /v1/auth/oidc/providers`; the login entry is `GET /v1/auth/oidc/generic/login` (307 to the IdP). id_tokens are verified against the IdP's JWKS (ES256/RS256) with iss/aud/exp/nonce checks.

## Feishu preset

Create an enterprise custom app on the [Feishu Open Platform](https://open.feishu.cn/document/sso/web-application-sso/login-overview), enable web authorization, and set the callback to `/v1/auth/oidc/feishu/callback`:

```bash
ARK_FEISHU_APP_ID=cli_xxx
ARK_FEISHU_APP_SECRET=...
```

Feishu uses OAuth2 authorization-code + user_info (union_id/open_id as the subject).

## JIT provisioning & governance

- First SSO login auto-creates the user (username from preferred_username/name, de-duplicated with a suffix); identity is uniquely linked by `(idp_provider, idp_subject)`
- SSO-created accounts have **unusable passwords** (random) — they can only sign in via SSO; disable/role changes go through the user-management API
- Provisioning is audited (`user.oidc_create`); repeat logins never duplicate accounts
- The local bootstrap admin is unaffected by SSO and serves as the break-glass path
