# SSO 接入(管理员)

Agentrum 的身份体系:**人**走 JWT(SSO 或账号密码),**机器**走项目 AK/SK。SSO 实现标准 OIDC——任何支持 discovery 的 IdP 都能接,飞书是内置预设;本地账号始终保留用于引导管理员。

## 通用 OIDC(推荐)

以 Keycloak / Casdoor / Authelia / Logto / Okta 等为例,在 IdP 建一个 OIDC 应用(回调地址填 `$ARK_OIDC_REDIRECT_BASE/v1/auth/oidc/generic/callback`),然后:

```bash
ARK_OIDC_GENERIC_ISSUER=https://sso.internal/realms/acme   # 会自动 discovery
ARK_OIDC_GENERIC_CLIENT_ID=agentrum
ARK_OIDC_GENERIC_CLIENT_SECRET=...
ARK_OIDC_GENERIC_SCOPES="openid profile email"
ARK_OIDC_REDIRECT_BASE=https://registry.internal           # 回调基址
ARK_UI_ORIGIN=https://registry.internal                    # 登录完成后跳回的 UI 地址
```

校验端点:`GET /v1/auth/oidc/providers` 返回已启用的 provider 列表;登录入口 `GET /v1/auth/oidc/generic/login`(307 到 IdP)。id_token 用 IdP 的 JWKS 验签(ES256/RS256),校验 iss/aud/exp/nonce。

## 飞书预设

[飞书开放平台](https://open.feishu.cn/document/sso/web-application-sso/login-overview)创建企业自建应用,开通网页应用授权,回调地址同上(路径为 `/v1/auth/oidc/feishu/callback`):

```bash
ARK_FEISHU_APP_ID=cli_xxx
ARK_FEISHU_APP_SECRET=...
```

飞书走 OAuth2 授权码 + user_info 模式(以 union_id/open_id 为身份主键)。

## JIT 建号与治理

- 首次 SSO 登录自动创建用户(用户名取 preferred_username/name,冲突自动加后缀),身份以 `(idp_provider, idp_subject)` 唯一关联
- SSO 建出的账号**密码不可用**(随机),只能走 SSO;禁用/平台管理员授权在「用户管理」API 操作
- 建号动作记录审计(`user.oidc_create`);后续登录不重复建号
- 本地 bootstrap 管理员不受 SSO 影响,用于 IdP 故障时的兜底
