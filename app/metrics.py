"""Metrics for Prometheus on GET /metrics.

Prometheus must send  Authorization: Bearer <METRICS_TOKEN>.  If METRICS_TOKEN is not set the
endpoint is turned off (the Node version left it open in that case).
"""

import hmac

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app.config import settings
from app.database import engine
from app.errors import ApiError
from app.logging_config import security_event
from app.security import get_client_ip, limiter

REQUESTS = Counter("http_requests_total", "Requests handled by the API", ["method", "route", "status"])
DURATION = Histogram(
    "http_request_duration_seconds",
    "Response time of the API, in seconds",
    ["method", "route", "status"],
    buckets=[0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5],
)
DB_POOL = Gauge("db_pool_connections", "Connections to PostgreSQL: total, in_use and idle", ["state"])


def route_label(request: Request, status: int) -> str:
    """The route with its parameters (/staff/{user_id}), not the real URL: one series per route, not per id."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path.rstrip("/") or "/"
    return "not_found" if status == 404 else "other"


def observe_request(request: Request, status: int, seconds: float) -> None:
    labels = {"method": request.method, "route": route_label(request, status), "status": str(status)}
    REQUESTS.labels(**labels).inc()
    DURATION.labels(**labels).observe(seconds)


def _update_pool_gauges() -> None:
    pool = engine.pool
    try:
        in_use, idle = pool.checkedout(), pool.checkedin()
    except AttributeError:  # pools without these counters (tests)
        return
    DB_POOL.labels(state="in_use").set(in_use)
    DB_POOL.labels(state="idle").set(idle)
    DB_POOL.labels(state="total").set(in_use + idle)


router = APIRouter()


@router.get("/metrics", include_in_schema=False)
@limiter.exempt
def metrics(request: Request) -> Response:
    if settings.metrics_token is None:
        raise ApiError(404, "Route not found")
    expected = f"Bearer {settings.metrics_token}".encode()
    received = request.headers.get("authorization", "").encode()
    if not hmac.compare_digest(received, expected):
        security_event("metrics_denied", ip=get_client_ip(request))
        raise ApiError(401, "Invalid metrics token")
    _update_pool_gauges()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
