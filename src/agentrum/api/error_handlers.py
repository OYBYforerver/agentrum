"""Global error handlers: every failure surfaces as a machine-readable
{code, detail} envelope. Codes are stable identifiers for CLI/UI localization.
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentrum import errors


def install_error_handlers(app) -> None:  # pragma: no cover
    @app.exception_handler(errors.AgentrumError)
    async def _domain(request: Request, exc: errors.AgentrumError):
        # context keys must not be able to override the envelope itself
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "detail": exc.detail, **exc.context},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": f"http_{exc.status_code}", "detail": str(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        all_errors = exc.errors()
        first = all_errors[0] if all_errors else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        detail = f"{loc}: {first.get('msg', 'invalid')}"
        if len(all_errors) > 1:
            detail += f" (and {len(all_errors) - 1} more)"
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_request", "detail": detail},
        )
