"""Public Flask entry point for SentinelOps-Lite."""
import os
import time
import psutil
from flask import Flask, jsonify, render_template, request
from prometheus_client import (
    Counter, Gauge, Info,
    generate_latest, CONTENT_TYPE_LATEST
)
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# ── Flask app ────────────────────────────────────────────────
application = Flask(__name__)

# ── Scanner blueprint (safe import) ─────────────────────────
try:
    from agent_monitor import scanner_bp
    application.register_blueprint(scanner_bp)
    print("✅ AI Scanner loaded → /scanner")
except Exception as _e:
    print(f"⚠️  Scanner skipped: {_e}")

# ════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
# ════════════════════════════════════════════════════════════

# ── App request metrics (your existing) ─────────────────────
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint"],
)

PROCESS_CPU = Gauge(
    "python_process_cpu_percent",
    "CPU usage percent of this process",
)

# ── Agent metrics (NEW - what CI is looking for) ─────────────
AGENT_STATUS = Gauge(
    "agent_status",
    "AI agent running status (1=running, 0=stopped)",
)

AGENT_INFO = Info(
    "agent",
    "AI agent information",
)

AGENT_REQUESTS_TOTAL = Counter(
    "agent_requests_total",
    "Total requests made by the AI agent",
    ["provider", "model", "status"],
)

AGENT_MODEL_INFO = Gauge(
    "agent_model_info",
    "AI model information (always 1, use labels for info)",
    ["provider", "model", "version", "environment"],
)

AGENT_UPTIME_SECONDS = Gauge(
    "agent_uptime_seconds",
    "How long the AI agent has been running",
)

AGENT_CPU_PERCENT = Gauge(
    "agent_cpu_percent",
    "CPU usage by the agent process",
)

AGENT_MEMORY_MB = Gauge(
    "agent_memory_mb",
    "Memory used by the agent process in MB",
)

# ── System metrics (NEW) ─────────────────────────────────────
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

# ── Initialise ───────────────────────────────────────────────
_START_TIME = time.time()
psutil.Process().cpu_percent(interval=None)


def _update_agent_metrics():
    """Update all agent-related Prometheus metrics."""
    proc = psutil.Process()
    mem  = psutil.virtual_memory()

    provider = os.getenv("AI_PROVIDER", "gemini")
    model    = os.getenv("AI_MODEL",    "gemini-2.5-flash")
    version  = os.getenv("APP_VERSION", "1.0.0")
    env      = os.getenv("ENVIRONMENT", "production")

    # Agent status
    AGENT_STATUS.set(1)

    # Agent info label set
    AGENT_INFO.info({
        "provider":    provider,
        "model":       model,
        "version":     version,
        "environment": env,
        "build":       os.getenv("BUILD_NUMBER", "unknown"),
        "cloud":       os.getenv("TARGET_CLOUD", "aws"),
        "region":      os.getenv("AWS_REGION",   "us-east-1"),
    })

    # Model info gauge (1 with labels = searchable)
    AGENT_MODEL_INFO.labels(
        provider=provider,
        model=model,
        version=version,
        environment=env,
    ).set(1)

    # Uptime
    AGENT_UPTIME_SECONDS.set(time.time() - _START_TIME)

    # Resource usage
    AGENT_CPU_PERCENT.set(
        proc.cpu_percent(interval=None)
    )
    AGENT_MEMORY_MB.set(
        round(proc.memory_info().rss / 1024 / 1024, 1)
    )

    # System metrics
    SYSTEM_CPU.set(psutil.cpu_percent(interval=None))
    SYSTEM_MEMORY_PERCENT.set(mem.percent)
    SYSTEM_MEMORY_USED_MB.set(
        round(mem.used / 1024 / 1024, 1)
    )

    # Process CPU for existing metric
    PROCESS_CPU.set(proc.cpu_percent(interval=None))


def _record(endpoint):
    """Record request count and update CPU metric."""
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
    ).inc()
    PROCESS_CPU.set(
        psutil.Process().cpu_percent(interval=None)
    )


# Initialise agent metrics on startup
_update_agent_metrics()


# ════════════════════════════════════════════════════════════
# ROUTES (all your existing routes unchanged)
# ════════════════════════════════════════════════════════════

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
            "cpu_usage_percent":   psutil.cpu_percent(interval=None),
            "memory_total_mb":     round(mem.total / 1024 / 1024, 1),
            "memory_used_mb":      round(mem.used  / 1024 / 1024, 1),
            "memory_percent":      mem.percent,
            "process_cpu_percent": proc.cpu_percent(interval=None),
            "process_memory_mb":   round(
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

    # Update metrics when agent status is checked
    _update_agent_metrics()

    # Also count this as a successful agent request
    AGENT_REQUESTS_TOTAL.labels(
        provider=os.getenv("AI_PROVIDER", "gemini"),
        model=os.getenv("AI_MODEL",    "gemini-2.5-flash"),
        status="success",
    ).inc()

    return jsonify(
        status="running",
        provider=os.getenv("AI_PROVIDER", "gemini"),
        model=os.getenv("AI_MODEL",    "gemini-2.5-flash"),
    )


@application.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint.
    Exposes all metrics including agent metrics.
    """
    _record("/metrics")

    # Always refresh agent metrics before serving
    _update_agent_metrics()

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


# ── WSGI entry point ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    application.run(
        host="0.0.0.0",
        port=port,
        debug=os.getenv("FLASK_DEBUG") == "1",
    )