"""The app: wires routers, middleware, error handlers and logging together.

Run it with:  uvicorn app.main:app --reload --port 8000
"""

import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.errors import common_headers, register_error_handlers
from app.logging_config import request_log, setup_logging
from app.metrics import observe_request
from app.metrics import router as metrics_router
from app.routers import (
    attendance,
    audit,
    catalogs,
    corrections,
    daycares,
    movements,
    notices,
    reports,
    rooms,
    schedules,
    session,
    staff,
    time_records,
)
from app.security import get_client_ip, limiter

# "Today" and the late minutes use the daycares' time zone (also for code that uses local time)
os.environ.setdefault("TZ", settings.tz)

setup_logging()

app = FastAPI(
    title="Sonrisas de Cristal API",
    version="2.0.0",
    description="Staff, schedules, clock-ins and attendance for the daycares of Sonrisas de Cristal.",
    # The interactive docs are only for development
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.state.limiter = limiter
register_error_handlers(app)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Per request: an id, the client IP, one log line, metrics, and safe headers."""
    started = time.perf_counter()
    request.state.request_id = uuid.uuid4().hex[:12]
    request.state.client_ip = get_client_ip(request)
    status = 500  # if an unhandled error goes through, that is what the client gets
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers.update(common_headers(request.state.request_id))
        return response
    finally:
        elapsed = time.perf_counter() - started
        observe_request(request, status, elapsed)
        request_log.log(
            logging.INFO if status < 500 else logging.ERROR,
            "request",
            extra={
                "fields": {
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                    "user_id": getattr(request.state, "user_id", None),
                    "ip": request.state.client_ip,
                }
            },
        )


@app.get("/", tags=["Health"])
def root():
    return {"message": "Sonrisas de Cristal API is running"}


app.include_router(metrics_router)
app.include_router(session.router)
app.include_router(catalogs.router)
app.include_router(daycares.router)
app.include_router(rooms.router)
app.include_router(staff.router)
app.include_router(movements.router)
app.include_router(schedules.router)
app.include_router(time_records.router)
app.include_router(corrections.router)
app.include_router(attendance.router)
app.include_router(notices.router)
app.include_router(audit.router)
app.include_router(reports.router)
