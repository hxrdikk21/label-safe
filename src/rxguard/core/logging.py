"""
Structured logs for the API: one JSON object per line on stderr, ready for any log collector.

Each record carries the request ID set by ``RequestTracingMiddleware`` (also returned to clients as
``X-Request-ID``), so a user's error report can be matched to the server log.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": REQUEST_ID.get(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
