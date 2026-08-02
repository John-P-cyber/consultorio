"""Structured logs and low-cardinality metrics for production operations."""

from __future__ import annotations

import logging
import re
import sys
import time
from uuid import uuid4

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from config import APP_ENV, LOG_LEVEL, RELEASE_SHA, SERVICE_NAME
from logging_formatter import JsonFormatter


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HTTP_REQUESTS = Counter(
    "clinica_http_requests_total",
    "Total HTTP requests processed.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "clinica_http_request_duration_seconds",
    "HTTP request duration.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_IN_PROGRESS = Gauge(
    "clinica_http_requests_in_progress",
    "HTTP requests currently being processed.",
    ("method",),
)
BUILD_INFO = Gauge(
    "clinica_build_info",
    "Deployed build identification.",
    ("service", "environment", "release"),
)
BUILD_INFO.labels(SERVICE_NAME, APP_ENV, RELEASE_SHA).set(1)
DATABASE_READY = Gauge(
    "clinica_database_ready",
    "Whether the application can query its database (1 ready, 0 unavailable).",
)
DATABASE_READY.set(0)


def configurar_logging() -> logging.Logger:
    logger = logging.getLogger("clinica")
    logger.setLevel(LOG_LEVEL)
    logger.propagate = False
    if not any(getattr(handler, "clinica_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler.clinica_json = True
        logger.addHandler(handler)
    return logger


def request_id(request: Request) -> str:
    recebido = request.headers.get("X-Request-ID", "")
    return recebido if REQUEST_ID_PATTERN.fullmatch(recebido) else uuid4().hex


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if template else "<unmatched>"


def metrics_payload() -> bytes:
    return generate_latest()


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def monotonic_time() -> float:
    return time.perf_counter()
