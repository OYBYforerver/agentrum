from fastapi import APIRouter

from agentrum.api.routes import (
    access_keys,
    audit,
    auth,
    health,
    notifications,
    oidc,
    resources,
    subscriptions,
    teams,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(auth.router, prefix="/v1/auth", tags=["auth"])
api_router.include_router(oidc.router)
api_router.include_router(users.router, prefix="/v1/users", tags=["users"])
api_router.include_router(teams.router, prefix="/v1/teams", tags=["teams"])
api_router.include_router(access_keys.router, prefix="/v1/teams", tags=["access-keys"])
api_router.include_router(resources.router, prefix="/v1/resources", tags=["resources"])
api_router.include_router(subscriptions.router, tags=["subscriptions"])
api_router.include_router(notifications.router, prefix="/v1/notifications", tags=["notifications"])
api_router.include_router(audit.router, prefix="/v1/audit", tags=["audit"])
