"""HTTP middleware: request-id propagation, body size cap."""

import json
import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Accepts an incoming X-Request-ID or generates one; exposes it to logs
    (via `request_id_var`) and echoes it back on the response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests whose declared Content-Length exceeds the cap.

    Protects the JSONB-backed spec storage from accidental or malicious
    oversized payloads.
    """

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            logger = logging.getLogger("agentrum.http")
            logger.warning("request body too large: %s bytes", content_length)
            return JSONResponse(
                status_code=413,
                content={"detail": f"request body exceeds {self.max_bytes} bytes"},
            )
        return await call_next(request)


def request_id() -> str:
    return request_id_var.get()


def _json_safe(value: str) -> str:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)
