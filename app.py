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
from agent_monitor import application, scanner

# ── Import metrics from monitoring/metrics.py ─────────────────
# These feed all 4 Grafana dashboards:
#   - Application Dashboard  (app_requests_total, app_errors_total, etc.)
#   - Deployment Dashboard   (deployment_info, container_status, etc.)
#   - System Dashboard       (system_cpu_usage_percent, etc.)
#   - AI Agent Dashboard     (agent_state, agent_token_usage_total, etc.)
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
# Shared between _track_request_end (request thread)
# and start_metrics_updater (background thread)
APP_STATS_LOCK = threading.Lock()

# ── FIX 5: Lock for thread-safe scanner state mutations ───────
# Prevents RuntimeError when clear_data() runs mid-iteration
_SCANNER_LOCK = threading.Lock()

# ── FIX 7: Defer metrics init into app context ────────────────
# Ensures Flask app is fully ready before metrics updater starts.
# Previously called at module level before routes were registered.
with application.app_context():
    update_metrics()
    start_metrics_updater(interval=15)


# ══════════════════════════════════════════════════════════════
# SECTION 2 — PROMETHEUS REQUEST TRACKING
# Hooks into every request to populate:
#   - app_requests_total           (Application Dashboard panel 1)
#   - app_request_duration_seconds (Application Dashboard panel 3)
#   - http_status_codes_total      (Application Dashboard panel 4)
#   - app_errors_total             (Application Dashboard panel 2)
#   - app_exceptions_total         (Application Dashboard panel 9)
#   - APP_STATS dict               (internal counters)
# ══════════════════════════════════════════════════════════════


# ── Record request start time ─────────────────────────────────
@application.before_request
def _track_request_start():
    """Stamp every incoming request with its start time."""
    request._start_time = time.time()


# ── Record request end + update counters ─────────────────────
@application.after_request
def _track_request_end(response):
    """
    After every response, increment Prometheus counters.

    FIX 2: If _start_time is missing (before_request failed),
    skip duration observation instead of emitting a false 0.

    FIX 4: All APP_STATS writes are protected by APP_STATS_LOCK
    to prevent race conditions with the background updater thread.
    """
    try:
        # FIX 2: Guard against missing start time
        start = getattr(request, "_start_time", None)
        if start is None:
            return response

        duration = time.time() - start
        method   = request.method
        endpoint = request.path
        status   = str(response.status_code)

        # Prometheus counters
        app_requests_total.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        app_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)
        http_status_codes_total.labels(code=status).inc()

        if response.status_code >= 500:
            app_errors_total.inc()

        # FIX 4: Thread-safe APP_STATS update
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


# ── Main dashboard page ───────────────────────────────────────
@application.get("/")
def home():
    """Serve the main index.html dashboard page."""
    return render_template("index.html")


# ── Health check for ECS/Elastic Beanstalk ────────────────────
@application.get("/health")
def health_check():
    """Health check endpoint — returns 200 'Healthy'."""
    return Response("Healthy", status=200, content_type="text/plain")


# ── Prometheus scrape endpoint ────────────────────────────────
@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """
    Prometheus scrapes this endpoint to collect all metrics.
    Serves all metrics defined in monitoring/metrics.py:
      - app_*        → Application Dashboard
      - deployment_* → Deployment Dashboard
      - system_*     → System Dashboard
      - agent_*      → AI Agent Dashboard
    """
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


# ── Agents dashboard page ─────────────────────────────────────
@application.route("/dashboard/agents")
def agents_dashboard():
    """AI Agent Monitor dashboard page — reuses index.html."""
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════
# SECTION 4 — AGENT MONITOR ROUTES
# All routes below are linked to agent_monitor.py's scanner.
# ══════════════════════════════════════════════════════════════


# ── Scan for AI agents ────────────────────────────────────────
@application.route("/api/scan", methods=["POST"])
def scan_agents():
    """
    Scan for AI agents.
    POST body: {"agent_names": "gpt-agent.js, claude-handler.py",
                "agent_paths": "/src/agents, ./lib/ai"}

    FIX 1: Removed manual app_requests_total.inc() call.
    The _track_request_end after_request hook handles all routes
    uniformly — the manual call was creating duplicate metric counts.
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No JSON data provided", "success": False}), 400

        agent_names = data.get("agent_names", "")
        agent_paths = data.get("agent_paths", "")

        result = scanner.scan_agents(agent_names, agent_paths)

        return jsonify(result), 200 if result.get("success") else 400

    except Exception as e:
        application.logger.error(f"Scan error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e), "success": False}), 500


# ── Get complete dashboard data ───────────────────────────────
@application.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    """Get complete dashboard data from scanner."""
    try:
        return jsonify(scanner.get_dashboard_data()), 200
    except Exception as e:
        application.logger.error(f"Dashboard error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get system metrics ────────────────────────────────────────
@application.route("/api/metrics/system", methods=["GET"])
def get_system_metrics():
    """Get system metrics (CPU, memory, storage) from scanner."""
    try:
        return jsonify(scanner.get_system_metrics()), 200
    except Exception as e:
        application.logger.error(f"System metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get token metrics ─────────────────────────────────────────
@application.route("/api/metrics/tokens", methods=["GET"])
def get_token_metrics():
    """Get token usage metrics from scanner."""
    try:
        return jsonify(scanner.get_token_metrics()), 200
    except Exception as e:
        application.logger.error(f"Token metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get request metrics ───────────────────────────────────────
@application.route("/api/metrics/requests", methods=["GET"])
def get_request_metrics():
    """Get request metrics (RPM/RPH/RPD) from scanner."""
    try:
        return jsonify(scanner.get_request_metrics()), 200
    except Exception as e:
        application.logger.error(f"Request metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Get all scanned agents ────────────────────────────────────
@application.route("/api/agents", methods=["GET"])
def get_agents():
    """Get all scanned agents from scanner."""
    try:
        agents = [scanner._agent_to_dict(a) for a in scanner.agents]
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
        agent = next((a for a in scanner.agents if a.id == agent_id), None)
        if agent:
            return jsonify(scanner._agent_to_dict(agent)), 200
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

    FIX 6: Renamed local variable from 'requests_list' to
    'scanned_requests' to avoid shadowing the 'requests' library
    name if it is imported elsewhere in the project.
    """
    try:
        limit = request.args.get("limit", 20, type=int)
        scanned_requests = [
            scanner._request_to_dict(r) for r in scanner.requests[:limit]
        ]
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
    """Get provider information from scanner."""
    try:
        providers = scanner.providers
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
    """Get detailed text report from scanner."""
    try:
        return jsonify({
            "report":    scanner.get_detailed_report(),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get report error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Download report as JSON ───────────────────────────────────
@application.route("/api/report/download", methods=["GET"])
def download_report():
    """Download report as JSON file from scanner."""
    try:
        report_bytes = scanner.save_report()
        return send_file(
            io.BytesIO(report_bytes),
            mimetype="application/json",
            as_attachment=True,
            download_name=f"agent_report_{int(time.time())}.json"
        )
    except Exception as e:
        application.logger.error(f"Download report error: {e}")
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
            "total_requests": len(scanner.requests),
            "timestamp":      time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get status error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── Refresh metrics ───────────────────────────────────────────
@application.route("/api/refresh", methods=["POST"])
def refresh_metrics():
    """Refresh simulated metrics for current agents."""
    try:
        if scanner.agents:
            scanner._generate_metrics()
            return jsonify({
                "success": True,
                "metrics": {
                    "cpu":          scanner.metrics.cpu,
                    "memory":       scanner.metrics.memory,
                    "storage":      scanner.metrics.storage,
                    "used_tokens":  scanner.metrics.used_tokens,
                    "total_tokens": scanner.metrics.total_tokens,
                    "rpm":          scanner.metrics.rpm,
                    "rph":          scanner.metrics.rph,
                    "rpd":          scanner.metrics.rpd,
                },
                "timestamp": time.time()
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

    FIX 5: Use .clear() under _SCANNER_LOCK instead of replacing
    list references (scanner.agents = []).  Replacing references
    mid-iteration in another thread raises RuntimeError.
    .clear() empties the existing list object in-place so any
    thread holding a reference to it sees the cleared state safely.
    """
    try:
        with _SCANNER_LOCK:
            scanner.agents.clear()
            scanner.requests.clear()
            scanner.providers.clear()
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
#
# FIX 3: Merged the two conflicting handlers:
#   - @errorhandler(Exception)  ← was in Section 2
#   - @errorhandler(500)        ← was in original Section 5
# Flask resolves overlapping handlers unpredictably.
# One unified Exception handler now covers both cases,
# increments the Prometheus counter, logs the error,
# and returns a consistent JSON response.
# ══════════════════════════════════════════════════════════════


# ── Unified exception + 500 handler ──────────────────────────
@application.errorhandler(Exception)
def handle_exception(e):
    """
    Handle all unhandled exceptions.
    Increments Prometheus exception counter and returns JSON.
    Replaces both the old _track_exception and internal_error handlers.
    """
    try:
        app_exceptions_total.inc()
        with APP_STATS_LOCK:
            APP_STATS["exceptions"] += 1
    except Exception:
        pass

    application.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({"error": "Internal server error", "status": 500}), 500


# ── 404 handler ───────────────────────────────────────────────
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