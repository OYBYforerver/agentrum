# Permission model

Agentrum permissions have four orthogonal dimensions: **platform role × project role × resource visibility × AK/SK scopes**. Every mutation is audited.

## Platform role

| Capability | Platform admin | Regular user |
|---|---|---|
| Create projects | ✅ | ❌ |
| Designate project owner | ✅ (at creation) | ❌ |
| User management (create/disable/reset password/promote) | ✅ | ❌ |
| Audit query, notification pipeline observability | ✅ | ❌ |

## Project roles (owner / admin / publisher / developer / member)

| Operation | Owner/Admin | Publisher | Developer | Member |
|---|---|---|---|---|
| Manage members | ✅ | ❌ | ❌ | ❌ |
| Create/revoke project AK/SK | ✅ | ❌ | ❌ | ❌ |
| Transfer ownership | Owner only | ❌ | ❌ | ❌ |
| Publish/update resources (PUT) | ✅ | ✅ | ✅ | ❌ |
| **Manage Deployments** | ✅ | ✅ | ❌ | ❌ |
| Edit metadata (PATCH, no version) | ✅ | ✅ | ✅ | ❌ |
| **Soft-delete resources** | ✅ | ✅ | **❌** | ❌ |
| Approve subscription requests | ✅ | ❌ | ❌ | ❌ |
| Revoke grants | ✅ | ❌ | ❌ | ❌ |
| Create subscriptions | ✅ | ✅ | ✅ | ✅ |

Developer vs publisher boundary: publish yes, delete no, deployments no — misoperation protection and deployment-rights separation.

## Resource visibility (read)

| visibility | Who can read | Cross-project subscription |
|---|---|---|
| `internal` | All authenticated users | Instant |
| `restricted` | Owning project + granted projects | Owner admin approval |
| `private` (Prompt only) | Owning project members only | Not allowed |

## AK/SK scopes (machine credentials)

| scope | Allowed |
|---|---|
| `read` | Catalog discovery, subscription management |
| `publish` | Publish/update/delete Agent, MCPServer, Skill, Prompt, Secret |
| `deploy` | Publish/update/delete **Deployment** resources (triggers cluster reconciliation) |

Three locks always apply: project boundary, scope allowlist, resource visibility. Deployment resources require the dedicated `deploy` scope — publish rights do not include the right to run code in the cluster.

## Ownership

Each project has exactly one owner (designated at creation, transferable by the owner or a platform admin). The new owner becomes an admin member; the previous owner is demoted to member. Stored explicitly as `teams.owner_user_id`.

## Audit

All of the above mutations land in `audit_log` with actor, time, source IP and context; 180-day retention by default.
