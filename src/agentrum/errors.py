"""Domain errors. The FastAPI layer maps these to {code, detail} responses."""

from typing import Any


class AgentrumError(Exception):
    """Base class for domain errors."""

    code = "agentrum_error"
    status = 400

    def __init__(self, detail: str, *, code: str | None = None, **context: Any):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        self.context = context


class NotFoundError(AgentrumError):
    code = "not_found"
    status = 404


class PermissionDeniedError(AgentrumError):
    code = "forbidden"
    status = 403


class ConflictError(AgentrumError):
    code = "conflict"
    status = 409


class ValidationError(AgentrumError):
    code = "invalid_request"
    status = 400


class RateLimitedError(AgentrumError):
    code = "rate_limited"
    status = 429
