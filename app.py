"""
app.py
======
Flask entry point for SentinelOps-Lite.
Only routes and redirections live here.
All logic lives in agent_monitor.py.
"""

import os
import sys
import time
from pathlib import Path

from flask import render_template, Response, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# ── path setup ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── import application and blueprint from agent_monitor ───────
from agent_monitor import application, monitor_bp, scanner_bp

# ── import custom Prometheus metrics ──────────────────────────
from monitoring.metrics import (
    start_metrics_updater,
    update_metrics,
    app_requests_total,
    app_request_duration_seconds,
    app_errors_total,
    app_exceptions_total,
    http_status_codes_total,
    APP_STATS,
)

# ── register blueprints ───────────────────────────────────────
application.register_blueprint(monitor_bp)
application.register_blueprint(scanner_bp)

# ── start metrics background updater ──────────────────────────
update_metrics()
start_metrics_updater(interval=5)


# ══════════════════════════════════════════════════════════════
# REQUEST TRACKING — populates app_* metrics for Grafana
# ══════════════════════════════════════════════════════════════


@application.before_request
def _track_request_start():
    """Record when each request started."""
    request._start_time = time.time()


@application.after_request
def _track_request_end(response):
    """Increment Prometheus counters after every request."""
    try:
        duration = time.time() - getattr(request, "_start_time", time.time())
        method = request.method
        endpoint = request.path
        status = str(response.status_code)

        # Increment counters
        app_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        app_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
        http_status_codes_total.labels(code=status).inc()

        if response.status_code >= 500:
            app_errors_total.inc()

        # Update APP_STATS for dashboard JSON snapshots
        APP_STATS["total_requests"] += 1
        APP_STATS["total_request_time"] += duration
        if response.status_code < 400:
            APP_STATS["success_requests"] += 1
        else:
            APP_STATS["failed_requests"] += 1
    except Exception:
        pass

    return response


@application.errorhandler(Exception)
def _track_exception(e):
    """Count uncaught exceptions."""
    try:
        app_exceptions_total.inc()
        APP_STATS["exceptions"] += 1
    except Exception:
        pass
    return Response("Internal Server Error", status=500)


# ══════════════════════════════════════════════════════════════
# ROUTES  —  only links and redirections live here
# ══════════════════════════════════════════════════════════════


@application.get("/")
def home():
    """Main dashboard page."""
    return render_template("index.html")


@application.post("/monitor/status", methods=["GET", "POST"])
def monitor_status():
    """
    CI / monitoring webhook.
    Delegates entirely to agent_monitor.handle_monitor_status().
    """
    from agent_monitor import handle_monitor_status
    return handle_monitor_status()


@application.get("/health")
def health_check():
    """Health check endpoint."""
    return Response("Healthy", status=200, content_type="text/plain")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """Prometheus scrape endpoint."""
    return Response(
        generate_latest(),
        content_type=CONTENT_TYPE_LATEST,
    )


# ══════════════════════════════════════════════════════════════
# WSGI entry point
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)
