"""HTTP middleware: request-id propagation, body size cap, security headers,
optional static hosting of the built web console."""

import json
import logging
import re
import uuid
from contextvars import ContextVar
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Header values end up in logs and response headers; keep them inert.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Paths that must always fall through to the API / MCP router even if a file
# of the same name happens to exist in the UI directory.
_RESERVED_PREFIXES = ("v1/", "mcp", "docs", "openapi.json", "metrics", "handbook", "health")


def request_id() -> str:
    return request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Accepts an incoming X-Request-ID or generates one; exposes it to logs
    (via `request_id_var`) and echoes it back on the response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        if not _REQUEST_ID_RE.fullmatch(rid):
            rid = uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than the cap.

    Counts the actual bytes received rather than trusting Content-Length, so
    chunked transfer encoding (which carries no length header) is capped too.
    Pure ASGI: buffers the (bounded) body, then replays it to the router.
    """

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunks.append(message.get("body", b""))
            total += len(chunks[-1])
            if total > self.max_bytes:
                logger = logging.getLogger("agentrum.http")
                logger.warning("request body too large: >%s bytes", self.max_bytes)
                response = JSONResponse(
                    status_code=413,
                    content={
                        "code": "body_too_large",
                        "detail": f"request body exceeds {self.max_bytes} bytes",
                    },
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body"):
                break

        replayed = {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        first_pass = True

        async def replay_receive():  # type: ignore[no-untyped-def]
            nonlocal first_pass
            if first_pass:
                first_pass = False
                return replayed
            return await receive()

        await self.app(scope, replay_receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers on every response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


class StaticConsoleMiddleware:
    """Serves the built web console (Next.js static export) for `/` and for
    real files under the UI directory, letting every other request — including
    POST /mcp and unknown paths — fall through to the API/MCP router."""

    def __init__(self, app, ui_dir: str) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.root = Path(ui_dir).resolve()

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] == "http" and scope["method"] == "GET":
            target = self._resolve(scope.get("path", "/"))
            if target is not None:
                await FileResponse(target)(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _resolve(self, path: str):  # type: ignore[no-untyped-def]
        rel = path.lstrip("/")
        if rel == "":
            index = self.root / "index.html"
            return index if index.is_file() else None
        if rel.startswith(_RESERVED_PREFIXES):
            return None
        candidate = (self.root / rel).resolve()
        if not candidate.is_relative_to(self.root):
            return None
        if candidate.is_file():
            return candidate
        if (candidate / "index.html").is_file():
            return candidate / "index.html"
        return None


def _json_safe(value: str) -> str:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)
