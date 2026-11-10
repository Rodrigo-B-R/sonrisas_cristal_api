"""One error format for the whole API: {"error": "message", ...extra details}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DataError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.logging_config import error_log, security_event


class ApiError(Exception):
    """Raise it anywhere: the client gets {"error": message, **extra} with that status code."""

    def __init__(self, status_code: int, message: str, headers: dict | None = None, **extra):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.headers = headers
        self.extra = extra


def common_headers(request_id: str | None = None) -> dict[str, str]:
    """Headers every response carries, including the ones for unhandled errors
    (those are built outside the middleware, so the middleware cannot add them)."""
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
    if request_id:
        headers["X-Request-ID"] = request_id
    if settings.is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


def error_response(status_code: int, message: str, headers: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message, **extra}, headers=headers)


def _client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None) or (request.client.host if request.client else None)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.message, exc.headers, **exc.extra)


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    messages = {404: "Route not found", 405: "Method not allowed"}
    return error_response(exc.status_code, messages.get(exc.status_code) or str(exc.detail), exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for error in exc.errors():
        place, *path = error["loc"]
        if error["type"] == "json_invalid":
            message = "The body is not valid JSON"
        else:
            message = error["msg"].removeprefix("Value error, ")
        # The submitted value is not echoed back: it may be a password
        details.append({"in": place, "field": ".".join(str(part) for part in path), "message": message})
    return error_response(400, "Invalid data", details=details)


def _sqlstate(exc: Exception) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    code = _sqlstate(exc)
    text = str(exc.orig).lower()
    if code == "23505" or "unique constraint" in text:
        return error_response(409, "A record with that value already exists (for example, a repeated username or email)")
    if code == "23503" or "foreign key" in text:
        return error_response(409, "Cannot do this: it has related data")
    if code in ("23514", "23502") or "check constraint" in text or "not null" in text:
        return error_response(400, "The data does not meet the database rules")
    return await unhandled_error_handler(request, exc)


async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    return error_response(400, "The data does not meet the database rules")


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    security_event(
        "rate_limited",
        path=request.url.path,
        method=request.method,
        ip=_client_ip(request),
        limit=str(exc.limit.limit) if getattr(exc, "limit", None) else None,
    )
    return error_response(429, "Too many requests. Try again in a minute.", headers={"Retry-After": "60"})


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    # The details stay in the log; the client only gets a generic message and an id to quote.
    error_log.error(
        "unhandled_error",
        exc_info=exc,
        extra={"fields": {"request_id": request_id, "path": request.url.path, "method": request.method}},
    )
    return error_response(500, "Internal error", headers=common_headers(request_id), requestId=request_id)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(DataError, data_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
