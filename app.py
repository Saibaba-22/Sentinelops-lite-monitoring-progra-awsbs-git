"""
app.py
======
Flask entry point for SentinelOps-Lite with AI Agent Monitor.

Structure:
  - Section 1: Imports & Setup
  - Section 2: Prometheus Request Tracking (feeds monitoring/metrics.py)
  - Section 3: Original app.py Routes (index, health, metrics, dashboard)
  - Section 4: Agent Monitor Routes (linked to agent_monitor.py scanner)
  - Section 5: Error Handlers
  - Section 6: WSGI Entry Point

Fixes applied:
  - FIX 1: Removed duplicate Prometheus increment in scan_agents()
  - FIX 2: Silent zero-duration on missing _start_time now skips observe()
  - FIX 3: Merged conflicting Exception + 500 error handlers into one
  - FIX 4: APP_STATS writes are now protected by threading.Lock
  - FIX 5: clear_data() uses .clear() under lock instead of list replacement
  - FIX 6: Renamed 'requests_list' shadow variable to 'scanned_requests'
  - FIX 7: update_metrics() deferred into app_context after app is ready
  - FIX 8: Removed duplicate /api/dashboard route (lives in agent_monitor.py)
  - FIX 9: Removed duplicate /api/report/download route (lives in agent_monitor.py)
"""

import os
import sys
import time
import io
import threading
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# SECTION 1 — IMPORTS & SETUP
# ══════════════════════════════════════════════════════════════

# ── Flask and Prometheus imports ──────────────────────────────
from flask import render_template, Response, request, jsonify, send_file
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# ── Path setup ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── Import Flask app + scanner from agent_monitor.py ─────────
# agent_monitor.py creates:
#   application = Flask(__name__)   ← the WSGI app
#   scanner     = AIAgentScanner()  ← scan/metrics logic
#
# Routes already registered in agent_monitor.py:
#   GET  /api/providers/models   → get_providers_models()
#   POST /api/scan/project       → scan_project()
#   POST /api/agent/test         → test_agent()
#   GET  /api/dashboard          → get_dashboard()      ← DO NOT duplicate
#   GET  /api/report/download    → download_report()    ← DO NOT duplicate
#   GET  /                       → index() inline HTML  ← overridden below
from agent_monitor import application, scanner

# ── Import metrics from monitoring/metrics.py ─────────────────
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

# ── FIX 4: Lock for thread-safe APP_STATS writes ─────────────
APP_STATS_LOCK = threading.Lock()

# ── FIX 5: Lock for thread-safe scanner state mutations ───────
_SCANNER_LOCK = threading.Lock()

# ── FIX 7: Defer metrics init into app context ────────────────
with application.app_context():
    update_metrics()
    start_metrics_updater(interval=15)


# ══════════════════════════════════════════════════════════════
# SECTION 2 — PROMETHEUS REQUEST TRACKING
# ══════════════════════════════════════════════════════════════

@application.before_request
def _track_request_start():
    """Stamp every incoming request with its start time."""
    request._start_time = time.time()


@application.after_request
def _track_request_end(response):
    """
    After every response, increment Prometheus counters.
    FIX 2: If _start_time is missing, skip duration observation.
    FIX 4: All APP_STATS writes protected by APP_STATS_LOCK.
    """
    try:
        start = getattr(request, "_start_time", None)
        if start is None:
            return response

        duration = time.time() - start
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

        with APP_STATS_LOCK:
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
# SECTION 3 — ORIGINAL app.py ROUTES
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home():
    """
    Serve the main index.html dashboard page.
    Overrides the inline HTML_TEMPLATE route in agent_monitor.py.
    """
    return render_template("index.html")


@application.get("/health")
def health_check():
    """Health check endpoint — returns 200 'Healthy'."""
    return Response("Healthy", status=200, content_type="text/plain")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """
    Prometheus scrape endpoint — DO NOT MODIFY.
    Serves all metrics defined in monitoring/metrics.py.
    """
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@application.route("/dashboard/agents")
def agents_dashboard():
    """AI Agent Monitor dashboard page — reuses index.html."""
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════
# SECTION 4 — AGENT MONITOR ROUTES
# Linked to agent_monitor.py scanner.
#
# NOTE: The following routes are already registered in
# agent_monitor.py and are NOT repeated here:
#   GET  /api/providers/models  → get_providers_models()
#   POST /api/scan/project      → scan_project()
#   POST /api/agent/test        → test_agent()
#   GET  /api/dashboard         → get_dashboard()
#   GET  /api/report/download   → download_report()
# ══════════════════════════════════════════════════════════════


# ── Get system metrics ────────────────────────────────────────
@application.route("/api/metrics/system", methods=["GET"])
def get_system_metrics():
    """Get system metrics (CPU, memory, storage) from scanner."""
    try:
        return jsonify(scanner.get_dashboard_data()["system_metrics"]), 200
    except Exception as e:
        application.logger.error(f"System metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get token metrics ─────────────────────────────────────────
@application.route("/api/metrics/tokens", methods=["GET"])
def get_token_metrics():
    """Get token usage metrics from scanner."""
    try:
        data = scanner.get_dashboard_data()
        return jsonify(data["session_stats"]), 200
    except Exception as e:
        application.logger.error(f"Token metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get request metrics ───────────────────────────────────────
@application.route("/api/metrics/requests", methods=["GET"])
def get_request_metrics():
    """Get request metrics (RPM/RPH/RPD) from scanner."""
    try:
        data = scanner.get_dashboard_data()
        sess = data["session_stats"]
        return jsonify({
            "rpm":       sess.get("rpm", 0),
            "rph":       sess.get("rph", 0),
            "rpd":       sess.get("rpd", 0),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Request metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get all scanned agents ────────────────────────────────────
@application.route("/api/agents", methods=["GET"])
def get_agents():
    """Get all scanned agents from scanner."""
    try:
        data   = scanner.get_dashboard_data()
        agents = data["agents"]
        return jsonify({
            "agents":    agents,
            "count":     len(agents),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get agents error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get specific agent details ────────────────────────────────
@application.route("/api/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    """Get specific agent details by ID."""
    try:
        agent = next(
            (a for a in scanner.agents if a.id == agent_id), None
        )
        if agent:
            return jsonify(scanner._agent_dict(agent)), 200
        return jsonify({"error": "Agent not found"}), 404
    except Exception as e:
        application.logger.error(f"Get agent error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get request history ───────────────────────────────────────
@application.route("/api/requests", methods=["GET"])
def get_requests():
    """
    Get request history from scanner.
    FIX 6: Renamed local variable to 'scanned_requests'.
    """
    try:
        limit = request.args.get("limit", 20, type=int)
        data  = scanner.get_dashboard_data()
        scanned_requests = data["request_history"][:limit]
        return jsonify({
            "requests":  scanned_requests,
            "count":     len(scanned_requests),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get requests error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get provider information ──────────────────────────────────
@application.route("/api/providers", methods=["GET"])
def get_providers():
    """Get provider summary from scanner."""
    try:
        data      = scanner.get_dashboard_data()
        providers = data["providers"]
        return jsonify({
            "providers": providers,
            "count":     len(providers),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get providers error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get text report ───────────────────────────────────────────
@application.route("/api/report", methods=["GET"])
def get_report():
    """Get detailed report data from scanner."""
    try:
        data = scanner.get_dashboard_data()
        return jsonify({
            "report":    data,
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get report error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get scanner status ────────────────────────────────────────
@application.route("/api/status", methods=["GET"])
def get_status():
    """Get scanner running status."""
    try:
        return jsonify({
            "status":         "running",
            "agents_count":   len(scanner.agents),
            "active_agents":  sum(1 for a in scanner.agents if a.active),
            "total_requests": len(scanner.request_history),
            "timestamp":      time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get status error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Refresh metrics ───────────────────────────────────────────
@application.route("/api/refresh", methods=["POST"])
def refresh_metrics():
    """Refresh dashboard data for current agents."""
    try:
        data = scanner.get_dashboard_data()
        if scanner.agents:
            return jsonify({
                "success":        True,
                "system_metrics": data["system_metrics"],
                "session_stats":  data["session_stats"],
                "timestamp":      time.time()
            }), 200
        return jsonify({"error": "No agents to refresh"}), 400
    except Exception as e:
        application.logger.error(f"Refresh metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Clear all scanned data ────────────────────────────────────
@application.route("/api/clear", methods=["POST"])
def clear_data():
    """
    Clear all scanned agents, requests, and providers.
    FIX 5: Use .clear() under _SCANNER_LOCK.
    """
    try:
        with _SCANNER_LOCK:
            scanner.agents.clear()
            scanner.request_history.clear()
            scanner.quota_trackers.clear()
            scanner.project_files.clear()
        return jsonify({
            "success":   True,
            "message":   "Data cleared",
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Clear data error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
# SECTION 5 — ERROR HANDLERS
# FIX 3: Merged conflicting Exception + 500 handlers into one.
# ══════════════════════════════════════════════════════════════

@application.errorhandler(Exception)
def handle_exception(e):
    """Handle all unhandled exceptions."""
    try:
        app_exceptions_total.inc()
        with APP_STATS_LOCK:
            APP_STATS["exceptions"] += 1
    except Exception:
        pass
    application.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"error": "Internal server error", "status": 500}), 500


@application.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Not found", "status": 404}), 404


# ══════════════════════════════════════════════════════════════
# SECTION 6 — WSGI ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)