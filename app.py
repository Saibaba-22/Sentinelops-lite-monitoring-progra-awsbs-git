"""
app.py
======
Thin WSGI entry point for SentinelOps-Lite.

- Imports Flask app + scanner from agent_monitor.py
- Adds Prometheus request tracking middleware
- Adds /metrics scrape endpoint
- Adds / and /dashboard/agents routes (index.html)
- Does NOT duplicate routes already in agent_monitor.py
"""

import os
import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── Flask imports ─────────────────────────────────────────────
from flask import Response, request, render_template

# ── Prometheus imports ────────────────────────────────────────
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# ── Import app + scanner from agent_monitor.py ────────────────
# agent_monitor.py already defines:
#   application = Flask(__name__)
#   scanner     = AIAgentScanner()
# and registers: /health, /api/*, errorhandler(404), errorhandler(500)
from agent_monitor import application, scanner

# ── Import Prometheus metrics from monitoring/metrics.py ──────
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

# ── Start background metrics updater thread ───────────────────
# Refreshes system/process gauges every 15 seconds
update_metrics()
start_metrics_updater(interval=15)


# ══════════════════════════════════════════════════════════════
# SECTION 1 — ROUTES
# Only routes NOT already in agent_monitor.py
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home():
    """Main dashboard — serves index.html."""
    return render_template("index.html")


@application.get("/dashboard/agents")
def agents_dashboard():
    """AI Agent Monitor dashboard — serves index.html."""
    return render_template("index.html")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """
    Prometheus scrape endpoint.
    Serves all metrics from monitoring/metrics.py:
      app_*        → Application Dashboard
      deployment_* → Deployment Dashboard
      system_*     → System Dashboard
      agent_*      → AI Agent Dashboard
    """
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


# ══════════════════════════════════════════════════════════════
# SECTION 2 — PROMETHEUS REQUEST TRACKING MIDDLEWARE
# Hooks into every request/response cycle
# ══════════════════════════════════════════════════════════════

@application.before_request
def _track_request_start():
    """Stamp every incoming request with its start time."""
    request._start_time = time.time()


@application.after_request
def _track_request_end(response):
    """After every response, increment Prometheus counters."""
    try:
        duration = time.time() - getattr(request, "_start_time", time.time())
        method   = request.method
        endpoint = request.path
        status   = str(response.status_code)

        app_requests_total.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        app_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)
        http_status_codes_total.labels(code=status).inc()

        if response.status_code >= 500:
            app_errors_total.inc()

        APP_STATS["total_requests"]     += 1
        APP_STATS["total_request_time"] += duration
        if response.status_code < 400:
            APP_STATS["success_requests"] += 1
        else:
            APP_STATS["failed_requests"]  += 1
    except Exception:
        pass

    return response


# ══════════════════════════════════════════════════════════════
# SECTION 3 — WSGI ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)