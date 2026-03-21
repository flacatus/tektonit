"""Observability: structured logging, Prometheus metrics, health checks.

Provides production-grade monitoring for Kubernetes deployment.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock, Thread

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

log = logging.getLogger("tektonit")

# -- Prometheus Metrics ------------------------------------------------------

LLM_CALL_DURATION = Histogram(
    "tekton_agent_llm_call_seconds",
    "LLM API call latency",
    labelnames=["provider", "operation"],
    buckets=(1, 5, 10, 30, 60, 120, 300),
)

LLM_TOKENS = Counter(
    "tekton_agent_llm_tokens_total",
    "LLM tokens consumed",
    labelnames=["provider", "direction"],
)

TESTS_GENERATED = Counter(
    "tekton_agent_tests_generated_total",
    "BATS test files generated",
    labelnames=["kind", "result"],
)

TESTS_FIXED = Counter(
    "tekton_agent_tests_fixed_total",
    "Test fix attempts by LLM",
    labelnames=["kind", "result"],
)

PRS_CREATED = Counter(
    "tekton_agent_prs_created_total",
    "Pull requests created",
    labelnames=["kind", "test_status"],
)

CYCLE_DURATION = Histogram(
    "tekton_agent_cycle_seconds",
    "Full monitoring cycle duration",
    buckets=(30, 60, 120, 300, 600, 1800, 3600),
)

RESOURCES_GAUGE = Gauge(
    "tekton_agent_resources",
    "Resource counts",
    labelnames=["category"],
)

ERRORS = Counter(
    "tekton_agent_errors_total",
    "Errors by type",
    labelnames=["component", "error_type"],
)


# -- Structured Logging ------------------------------------------------------

class _JSONFormatter(logging.Formatter):
    """JSON log formatter for Kubernetes log aggregation."""

    def format(self, record):
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        # Add extra fields
        for key in ("resource", "kind", "pr_url", "duration", "tokens"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        return json.dumps(entry, default=str)


def setup_logging(json_format: bool | None = None):
    """Configure logging. Uses JSON in containers, text locally."""
    if json_format is None:
        # Auto-detect: JSON in containers, text in terminals
        json_format = not sys.stderr.isatty()

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
    root.addHandler(handler)


# -- Health Server -----------------------------------------------------------

_status_lock = Lock()
_last_cycle_status: dict = {"status": "starting", "ts": time.time()}
_state_store = None


def update_status(status: dict):
    """Thread-safe status update."""
    with _status_lock:
        global _last_cycle_status
        status["ts"] = time.time()
        _last_cycle_status = status


def get_status() -> dict:
    with _status_lock:
        return dict(_last_cycle_status)


def set_state_store(store):
    """Register state store for health endpoint stats."""
    global _state_store
    _state_store = store


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            status = get_status()
            # Detect stale: if no update in 2x poll interval, unhealthy
            poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "3600"))
            age = time.time() - status.get("ts", 0)
            healthy = age < (poll_interval * 2 + 600)  # 2 cycles + 10min buffer

            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = {"healthy": healthy, "age_seconds": int(age), **status}
            if _state_store:
                body["stats"] = _state_store.get_stats()
            self.wfile.write(json.dumps(body).encode())

        elif self.path == "/readyz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        elif self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(generate_latest())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server(port: int = 8080):
    """Start the health/metrics HTTP server in a daemon thread."""
    try:
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info("Health server on :%d (/healthz, /readyz, /metrics)", port)
    except Exception as e:
        log.warning("Health server failed to start: %s (non-fatal)", e)
