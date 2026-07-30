"""Public Flask entry point for SentinelOps-Lite."""
import os
import time
import psutil
from flask import Flask, jsonify, render_template, request
from prometheus_client import (
    make_wsgi_app, Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from werkzeug.middleware.dispatcher import DispatcherMiddleware

application = Flask(__name__)

# ── Prometheus metrics ──────────────────────────────────────
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint"],
)
PROCESS_CPU = Gauge(
    "python_process_cpu_percent",
    "CPU usage percent of this process",
)

# Initialise CPU percent (first call always returns 0.0)
psutil.Process().cpu_percent(interval=None)


def _record(endpoint):
    REQUEST_COUNT.labels(method=request.method, endpoint=endpoint).inc()
    PROCESS_CPU.set(psutil.Process().cpu_percent(interval=None))


# ── Routes ──────────────────────────────────────────────────

@application.get("/")
def home():
    _record("/")
    return render_template("index.html")


@application.get("/health")
def health():
    _record("/health")
    return render_template("index.html")


@application.get("/api")
def api():
    _record("/api")
    return jsonify(
        message="Hello from SentinelOps-Lite!",
        status="running",
        version=os.getenv("APP_VERSION", "1.0.0"),
        build=os.getenv("BUILD_NUMBER", "unknown"),
    )


@application.get("/api/status")
def api_status():
    _record("/api/status")
    proc = psutil.Process()
    mem  = psutil.virtual_memory()
    return jsonify(
        application={
            "name":    "SentinelOps-Lite",
            "version": os.getenv("APP_VERSION", "1.0.0"),
            "build":   os.getenv("BUILD_NUMBER", "unknown"),
            "env":     os.getenv("ENVIRONMENT", "production"),
        },
        system={
            "cpu_usage_percent":    psutil.cpu_percent(interval=None),
            "memory_total_mb":      round(mem.total / 1024 / 1024, 1),
            "memory_used_mb":       round(mem.used  / 1024 / 1024, 1),
            "memory_percent":       mem.percent,
            "process_cpu_percent":  proc.cpu_percent(interval=None),
            "process_memory_mb":    round(
                proc.memory_info().rss / 1024 / 1024, 1
            ),
        },
        agent={
            "provider": os.getenv("AI_PROVIDER", "gemini"),
            "model":    os.getenv("AI_MODEL",    "gemini-2.5-flash"),
        },
        deployment={
            "version": os.getenv("APP_VERSION", "1.0.0"),
            "build":   os.getenv("BUILD_NUMBER", "unknown"),
            "cloud":   os.getenv("TARGET_CLOUD", "aws"),
            "region":  os.getenv("AWS_REGION",   "us-east-1"),
        },
    )


@application.get("/agent/status")
def agent_status():
    _record("/agent/status")
    return jsonify(
        status="running",
        provider=os.getenv("AI_PROVIDER", "gemini"),
        model=os.getenv("AI_MODEL",    "gemini-2.5-flash"),
    )


@application.get("/metrics")
def metrics():
    _record("/metrics")
    PROCESS_CPU.set(psutil.Process().cpu_percent(interval=None))
    return application.response_class(
        generate_latest(),
        mimetype=CONTENT_TYPE_LATEST,
    )


@application.post("/monitor/status")
def monitor_status():
    token = os.getenv("MONITOR_TOKEN", "")
    if token and request.headers.get("X-Monitor-Token") != token:
        return jsonify(error="unauthorized"), 401
    return jsonify(ok=True)


# ── WSGI entry point ────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    application.run(
        host="0.0.0.0",
        port=port,
        debug=os.getenv("FLASK_DEBUG") == "1",
    )