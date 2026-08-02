"""Bootstrap-safe JSON formatter used before application configuration loads."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime


LOG_FIELDS = (
    "request_id",
    "method",
    "route",
    "status",
    "duration_ms",
    "event",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    """Format one JSON object per line without clinical or personal data.

    This module deliberately does not import ``config``. Uvicorn initializes its
    logging before importing the FastAPI application, so a configuration error
    must remain visible instead of being wrapped as a logging formatter error.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "service": os.getenv("SERVICE_NAME", "consultorio-api"),
            "environment": os.getenv("APP_ENV", "development"),
            "release": os.getenv("RELEASE_SHA") or os.getenv("RENDER_GIT_COMMIT", "local"),
        }
        for field in LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
