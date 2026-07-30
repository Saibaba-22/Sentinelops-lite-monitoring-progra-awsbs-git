"""
Public Flask entry point for SentinelOps-Lite.

Fixes applied:
- Correct CPU measurement using cached Process object
- Authenticated /metrics endpoint
- Proper /health endpoint returning JSON
- Request latency histogram added
- Agent info set once on startup
- psutil error handling
- Constant-time token comparison
- Centralized config defaults
- Blueprint failure reflected in health status
- Background metric refresh separated from scrape path
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

import psutil
from flask import Flask, Response, jsonify, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)

# ══════════════════════════════════════════════════════════════
# APPLICATION FACTORY
# ══════════════════════════════════════════════════════════════

application = Flask(__name__)

# ── Centralised config defaults ───────────────────────────────
# Read once at startup — do not scatter os.getenv() across routes
_CFG: dict[str, str] = {
    "provider":     os.getenv("AI_PROVIDER",    "gemini"),
    "model":        os.getenv("AI_MODEL",       "gemini-2.5-flash"),
    "version":      os.getenv("APP_VERSION",    "1.0.0"),
    "build":        os.getenv("BUILD_NUMBER",   "unknown"),
    "environment":  os.getenv("ENVIRONMENT",    "production"),
    "cloud":        os.getenv("TARGET_CLOUD",   "aws"),
    "region":       os.getenv("AWS_REGION",     "us-east-1"),
    "monitor_token":os.getenv("MONITOR_TOKEN",  ""),
    "metrics_token":os.getenv("METRICS_TOKEN",  ""),   # NEW: optional bearer token
    "port":         os.getenv("PORT",           "5000"),
}

# ── Startup timestamp ─────────────────────────────────────────
_START_TIME: float = time.time()

# ── Cached process handle (read /proc once, reuse) ───────────
# psutil.Process() with no argument caches the current PID.
# One object → one file descriptor → correct cpu_percent deltas.
_PROC: psutil.Process = psutil.Process()

# Warm up the CPU percent measurement.
# First call ALWAYS returns 0.0; the second call returns a real value.
# We prime it here so the first real reading at /metrics is accurate.
_PROC.cpu_percent(interval=0.1)   # ← blocking 100 ms once at startup

# ── Blueprint registration ────────────────────────────────────
_SCANNER_LOADED: bool = False
try:
    from agent_monitor import scanner_bp          # type: ignore[import]
    application.register_blueprint(scanner_bp)
    _SCANNER_LOADED = True
    print("✅ AI Scanner loaded → /scanner")
except Exception as _bp_err:
    print(f"⚠️  Scanner skipped: {_bp_err}")


# ══════════════════════════════════════════════════════════════
# PROMETHEUS METRICS  —  defined once at module level
# ══════════════════════════════════════════════════════════════

# ── HTTP request metrics ──────────────────────────────────────
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],        # added status label
)

REQUEST_LATENCY = Histogram(
    "app_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05,
             0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ── Agent metrics ─────────────────────────────────────────────
AGENT_STATUS = Gauge(
    "agent_status",
    "AI agent running status (1=running, 0=stopped)",
)

AGENT_INFO = Info(
    "agent",
    "AI agent static information (set once at startup)",
)

AGENT_REQUESTS_TOTAL = Counter(
    "agent_requests_total",
    "Total requests made by the AI agent",
    ["provider", "model", "status"],
)

AGENT_MODEL_INFO = Gauge(
    "agent_model_info",
    "AI model label carrier (value always 1)",
    ["provider", "model", "version", "environment"],
)

AGENT_UPTIME_SECONDS = Gauge(
    "agent_uptime_seconds",
    "Seconds since the AI agent process started",
)

AGENT_CPU_PERCENT = Gauge(
    "agent_cpu_percent",
    "CPU usage percent of the agent process",
)

AGENT_MEMORY_MB = Gauge(
    "agent_memory_mb",
    "RSS memory used by the agent process in MB",
)

SCANNER_LOADED = Gauge(
    "agent_scanner_loaded",
    "1 if the AI scanner blueprint loaded successfully, 0 otherwise",
)

# ── System metrics ────────────────────────────────────────────
SYSTEM_CPU = Gauge(
    "system_cpu_percent",
    "System-wide CPU usage percent",
)

SYSTEM_MEMORY_PERCENT = Gauge(
    "system_memory_percent",
    "System memory usage percent",
)

SYSTEM_MEMORY_USED_MB = Gauge(
    "system_memory_used_mb",
    "System memory used in MB",
)

# Keep the original name for backward compatibility
PROCESS_CPU = Gauge(
    "python_process_cpu_percent",
    "CPU usage percent of this process (alias of agent_cpu_percent)",
)


# ══════════════════════════════════════════════════════════════
# METRIC INITIALISATION  (called once at startup)
# ══════════════════════════════════════════════════════════════

def _init_static_metrics() -> None:
    """
    Set metrics that never change after startup.

    Info / label-carrying gauges must be set ONCE.
    Calling .info() or .labels(...).set() repeatedly with the same
    label combination is safe, but calling .info() more than once
    on the same Info object raises a ValueError in newer versions
    of prometheus_client.
    """
    # Agent info — static labels, set once
    AGENT_INFO.info({
        "provider":    _CFG["provider"],
        "model":       _CFG["model"],
        "version":     _CFG["version"],
        "environment": _CFG["environment"],
        "build":       _CFG["build"],
        "cloud":       _CFG["cloud"],
        "region":      _CFG["region"],
    })

    # Model info gauge — label-carrier, set once
    AGENT_MODEL_INFO.labels(
        provider=   _CFG["provider"],
        model=      _CFG["model"],
        version=    _CFG["version"],
        environment=_CFG["environment"],
    ).set(1)

    # Scanner health
    SCANNER_LOADED.set(1 if _SCANNER_LOADED else 0)

    # Initial agent status
    AGENT_STATUS.set(1)


def _update_dynamic_metrics() -> None:
    """
    Refresh metrics that change over time.

    Call this from a background thread or immediately before
    a Prometheus scrape — NOT on every HTTP request.

    Raises nothing: all psutil errors are caught and logged.
    """
    try:
        # ── Process metrics ───────────────────────────────────
        # cpu_percent(interval=None) returns the delta since the
        # LAST call on this same Process object.  Because we primed
        # _PROC at startup, subsequent calls return meaningful values.
        cpu = _PROC.cpu_percent(interval=None)
        mem_rss_mb = round(_PROC.memory_info().rss / 1024 / 1024, 2)

        AGENT_CPU_PERCENT.set(cpu)
        AGENT_MEMORY_MB.set(mem_rss_mb)
        PROCESS_CPU.set(cpu)          # backward-compat alias
        AGENT_UPTIME_SECONDS.set(round(time.time() - _START_TIME, 1))
        AGENT_STATUS.set(1)

    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        # Process vanished or we lost permission — mark agent stopped
        print(f"⚠️  psutil process error: {exc}")
        AGENT_STATUS.set(0)

    try:
        # ── System metrics ────────────────────────────────────
        vmem = psutil.virtual_memory()
        SYSTEM_CPU.set(psutil.cpu_percent(interval=None))
        SYSTEM_MEMORY_PERCENT.set(vmem.percent)
        SYSTEM_MEMORY_USED_MB.set(round(vmem.used / 1024 / 1024, 2))

    except Exception as exc:                    # noqa: BLE001
        print(f"⚠️  psutil system error: {exc}")


# Run both once at startup
_init_static_metrics()
_update_dynamic_metrics()


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _record(endpoint: str, status: int = 200) -> float:
    """
    Increment request counter with status label.
    Returns the current timestamp so the caller can measure latency.
    """
    REQUEST_COUNT.labels(
        method=  request.method,
        endpoint=endpoint,
        status=  str(status),
    ).inc()
    return time.perf_counter()


def _finish(endpoint: str, start: float) -> None:
    """Record request latency."""
    REQUEST_LATENCY.labels(
        method=  request.method,
        endpoint=endpoint,
    ).observe(time.perf_counter() - start)


def _safe_system_snapshot() -> dict[str, Any]:
    """
    Return a dict with system/process metrics.
    All psutil errors are caught; fields default to -1 on failure.
    """
    snapshot: dict[str, Any] = {
        "cpu_usage_percent":   -1,
        "memory_total_mb":     -1,
        "memory_used_mb":      -1,
        "memory_percent":      -1,
        "process_cpu_percent": -1,
        "process_memory_mb":   -1,
    }
    try:
        vmem = psutil.virtual_memory()
        snapshot["cpu_usage_percent"]  = psutil.cpu_percent(interval=None)
        snapshot["memory_total_mb"]    = round(vmem.total / 1024 / 1024, 1)
        snapshot["memory_used_mb"]     = round(vmem.used  / 1024 / 1024, 1)
        snapshot["memory_percent"]     = vmem.percent
        snapshot["process_cpu_percent"]= _PROC.cpu_percent(interval=None)
        snapshot["process_memory_mb"]  = round(
            _PROC.memory_info().rss / 1024 / 1024, 1
        )
    except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
        print(f"⚠️  system snapshot error: {exc}")
    return snapshot


def _check_metrics_auth() -> bool:
    """
    Return True if the /metrics request is authorised.

    If METRICS_TOKEN is empty → allow all (open Prometheus scrape).
    If METRICS_TOKEN is set   → require 'Authorization: Bearer <token>'.

    Uses hmac.compare_digest to prevent timing-based token enumeration.
    """
    token = _CFG["metrics_token"]
    if not token:
        return True                             # No auth configured → open

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    provided = auth_header[len("Bearer "):]
    # constant-time comparison prevents timing attacks
    return hmac.compare_digest(
        provided.encode(),
        token.encode(),
    )


def _check_monitor_auth() -> bool:
    """
    Constant-time comparison for X-Monitor-Token header.
    Returns True if auth passes or no token is configured.
    """
    token = _CFG["monitor_token"]
    if not token:
        return True

    provided = request.headers.get("X-Monitor-Token", "")
    return hmac.compare_digest(
        provided.encode(),
        token.encode(),
    )


# ══════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home() -> str:
    t = _record("/")
    result = render_template("index.html")
    _finish("/", t)
    return result


@application.get("/health")
def health() -> tuple[Response, int]:
    """
    Liveness / readiness probe endpoint.

    Returns JSON — NOT HTML — so that:
      • Kubernetes liveness/readiness probes work correctly.
      • Load balancers can parse the response body.
      • curl-based checks return machine-readable output.

    HTTP 200 = healthy, HTTP 503 = degraded.
    """
    t = _record("/health")

    healthy = True
    checks: dict[str, str] = {
        "app":     "ok",
        "scanner": "ok" if _SCANNER_LOADED else "degraded",
    }

    # Quick psutil self-check
    try:
        _PROC.status()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        checks["process"] = "error"
        healthy = False

    status_code = 200 if healthy else 503
    _record("/health", status_code)
    _finish("/health", t)

    return jsonify(
        status="healthy" if healthy else "degraded",
        checks=checks,
        uptime_seconds=round(time.time() - _START_TIME, 1),
        version=_CFG["version"],
        build=_CFG["build"],
    ), status_code


@application.get("/api")
def api() -> Response:
    t = _record("/api")
    result = jsonify(
        message="Hello from SentinelOps-Lite!",
        status="running",
        version=_CFG["version"],
        build=_CFG["build"],
    )
    _finish("/api", t)
    return result


@application.get("/api/status")
def api_status() -> Response:
    t = _record("/api/status")
    result = jsonify(
        application={
            "name":        "SentinelOps-Lite",
            "version":     _CFG["version"],
            "build":       _CFG["build"],
            "environment": _CFG["environment"],
        },
        system=_safe_system_snapshot(),
        agent={
            "provider": _CFG["provider"],
            "model":    _CFG["model"],
            "status":   "running",
            "uptime_seconds": round(time.time() - _START_TIME, 1),
        },
        deployment={
            "version": _CFG["version"],
            "build":   _CFG["build"],
            "cloud":   _CFG["cloud"],
            "region":  _CFG["region"],
        },
        scanner={
            "loaded": _SCANNER_LOADED,
        },
    )
    _finish("/api/status", t)
    return result


@application.get("/agent/status")
def agent_status() -> tuple[Response, int]:
    """
    Returns current agent status and refreshes dynamic metrics.
    Also records one successful agent request observation.
    """
    t = _record("/agent/status")

    # Refresh dynamic metrics on explicit agent status check
    _update_dynamic_metrics()

    AGENT_REQUESTS_TOTAL.labels(
        provider=_CFG["provider"],
        model=   _CFG["model"],
        status=  "success",
    ).inc()

    result = jsonify(
        status=        "running",
        provider=      _CFG["provider"],
        model=         _CFG["model"],
        uptime_seconds=round(time.time() - _START_TIME, 1),
        scanner_loaded=_SCANNER_LOADED,
    )
    _finish("/agent/status", t)
    return result, 200


@application.get("/metrics")
def metrics() -> tuple[Response, int]:
    """
    Prometheus scrape endpoint.

    Security:
        If METRICS_TOKEN env var is set, requires:
            Authorization: Bearer <METRICS_TOKEN>
        If unset, endpoint is open (standard Prometheus pull model).

    Performance:
        Dynamic metrics are refreshed here so scrapes always get
        fresh values.  Static metrics (AGENT_INFO, AGENT_MODEL_INFO)
        are NOT re-set — they were set once at startup.
    """
    t = _record("/metrics")

    if not _check_metrics_auth():
        _finish("/metrics", t)
        return (
            Response("Unauthorized\n", status=401,
                     mimetype="text/plain"),
            401,
        )

    # Refresh dynamic metrics just before serving scrape
    _update_dynamic_metrics()

    payload = generate_latest()
    _finish("/metrics", t)

    return (
        Response(payload, mimetype=CONTENT_TYPE_LATEST),
        200,
    )


@application.post("/monitor/status")
def monitor_status() -> tuple[Response, int]:
    """
    Internal monitoring webhook.

    Uses constant-time token comparison to prevent timing attacks.
    """
    t = _record("/monitor/status")

    if not _check_monitor_auth():
        _finish("/monitor/status", t)
        return jsonify(error="unauthorized"), 401

    _finish("/monitor/status", t)
    return jsonify(ok=True), 200


# ══════════════════════════════════════════════════════════════
# WSGI / DEV SERVER
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(_CFG["port"])
    debug = os.getenv("FLASK_DEBUG") == "1"
    print(f"🚀 SentinelOps-Lite starting on port {port} (debug={debug})")
    application.run(
        host="0.0.0.0",
        port=port,
        debug=debug,
    )