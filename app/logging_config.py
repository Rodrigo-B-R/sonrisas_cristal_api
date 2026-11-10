"""JSON logs: one line per event, easy to read by people and by tools (Grafana Loki, grep, jq).

Two loggers:
  app.request   one line per HTTP request (method, route, status, time, user, IP)
  app.security  things worth an alert: failed logins, lockouts, 401/403, rate limits,
                password changes and resets, role changes, terminations
Passwords and tokens are never logged.
"""

import json
import logging
import sys
from datetime import datetime, timezone

request_log = logging.getLogger("app.request")
security_log = logging.getLogger("app.security")
error_log = logging.getLogger("app.error")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        data.update(getattr(record, "fields", {}))
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        # json.dumps escapes newlines, so user input cannot forge a fake log line
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    for logger in (request_log, security_log, error_log):
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
    # We already log every request ourselves
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def clip(value: str | None, size: int = 64) -> str | None:
    """Shorten user-supplied text before it goes into a log."""
    return value if value is None or len(value) <= size else value[:size] + "…"


def security_event(event: str, level: int = logging.WARNING, **fields) -> None:
    security_log.log(level, event, extra={"fields": {"event": event, **fields}})
