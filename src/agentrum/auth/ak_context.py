"""Request-scoped AK/SK context (set by the auth dependency, read by the
authorization layer). Mirrors the request-id contextvar pattern."""

from contextvars import ContextVar

ak_project_id_var: ContextVar[str | None] = ContextVar("ak_project_id", default=None)
ak_scopes_var: ContextVar[tuple] = ContextVar("ak_scopes", default=())

AK_SCOPES = ("read", "publish", "deploy")


def ak_project_id() -> str | None:
    return ak_project_id_var.get()


def has_scope(scope: str) -> bool:
    return scope in ak_scopes_var.get()
