"""
app.py
======
Flask entry point for SentinelOps-Lite with AI Agent Monitor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BLOCK MAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BLOCK 1  ── Standard-library & third-party imports
  BLOCK 2  ── Path / sys.path setup
  BLOCK 3  ── Import classes from agent_monitor.py
  BLOCK 4  ── Import Prometheus counters from monitoring/metrics.py
  BLOCK 5  ── Thread-safety locks
  BLOCK 6  ── Deferred metrics init inside app context
  BLOCK 7  ── Prometheus request lifecycle hooks
  BLOCK 8  ── Core Flask routes (UNCHANGED)
               GET  /                  → index.html  (UNTOUCHED)
               GET  /health            → plain-text health check
               GET  /metrics           → Prometheus scrape endpoint
               GET  /dashboard/agents  → index.html alias
  BLOCK 9  ── Agent Monitor HTML routes (NEW - all return HTML)
               GET  /dashboard         → HTML dashboard
               GET  /files             → HTML files page
               GET  /agents            → HTML agents page
               GET  /monitor           → HTML metrics page
               GET  /model             → HTML model page
               GET  /history           → HTML history page
               GET  /scan              → trigger scan → HTML result
               GET  /reset             → reset data  → HTML result
  BLOCK 10 ── Agent Monitor API routes (JSON - scanner-backed)
               GET  /api/metrics/system
               GET  /api/metrics/tokens
               GET  /api/metrics/requests
               GET  /api/agents
               GET  /api/agents/<agent_id>
               GET  /api/requests
               GET  /api/providers
               GET  /api/report
               GET  /api/status
               POST /api/refresh
               POST /api/clear
  BLOCK 11 ── Error handlers
  BLOCK 12 ── WSGI / __main__ entry point
"""

# ══════════════════════════════════════════════════════════════
# BLOCK 1 — STANDARD-LIBRARY & THIRD-PARTY IMPORTS
# ══════════════════════════════════════════════════════════════

import os
import sys
import time
import threading
from pathlib import Path

from flask import (
    Flask,
    render_template,
    Response,
    request,
    jsonify,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


# ══════════════════════════════════════════════════════════════
# BLOCK 2 — PATH / sys.path SETUP
# ══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ══════════════════════════════════════════════════════════════
# BLOCK 3 — IMPORT CLASSES FROM agent_monitor.py
# ──────────────────────────────────────────────────────────────
# agent_monitor.py now contains ONLY classes — no HTTP server,
# no Flask app, no routes.
# We create the Flask app here and own ALL routes.
# ══════════════════════════════════════════════════════════════

from flask import Flask
application = Flask(__name__)

from agent_monitor import (
    MetricsDB,
    ProjectScanner,
    ResourceMonitor,
    HTMLBuilder,
    ACTIVE_CONFIG,
)

# ── Initialise components ─────────────────────────────────────
SCAN_PATH = os.environ.get("SCAN_PATH", str(BASE_DIR))

_db      = MetricsDB()
_scanner = ProjectScanner(_db)
_monitor = ResourceMonitor(_db)
_monitor.start_monitoring()

# ── Initial scan on startup ───────────────────────────────────
try:
    _scanner.scan_project(SCAN_PATH)
    print(f"[app] ✅ Initial scan complete: {SCAN_PATH}")
except Exception as _e:
    print(f"[app] ⚠ Initial scan error: {_e}")


# ══════════════════════════════════════════════════════════════
# BLOCK 4 — IMPORT PROMETHEUS COUNTERS
# ──────────────────────────────────────────────────────────────
# Unchanged — exactly as your original app.py had it.
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
# BLOCK 5 — THREAD-SAFETY LOCKS
# ══════════════════════════════════════════════════════════════

APP_STATS_LOCK = threading.Lock()   # protects APP_STATS dict
_SCANNER_LOCK  = threading.Lock()   # protects scanner collections


# ══════════════════════════════════════════════════════════════
# BLOCK 6 — DEFERRED METRICS INIT INSIDE APP CONTEXT
# ══════════════════════════════════════════════════════════════

with application.app_context():
    update_metrics()
    start_metrics_updater(interval=15)


# ══════════════════════════════════════════════════════════════
# BLOCK 7 — PROMETHEUS REQUEST LIFECYCLE HOOKS
# ──────────────────────────────────────────────────────────────
# Unchanged — exactly as your original app.py had it.
# ══════════════════════════════════════════════════════════════

@application.before_request
def _track_request_start():
    """Stamp every incoming request with its start time."""
    request._start_time = time.time()


@application.after_request
def _track_request_end(response):
    """Record duration, status, and APP_STATS for every response."""
    try:
        start = getattr(request, "_start_time", None)
        if start is None:
            return response

        duration = time.time() - start
        method   = request.method
        endpoint = request.path
        status   = str(response.status_code)

        # ── Prometheus counters / histogram ──────────────────
        app_requests_total.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        app_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)
        http_status_codes_total.labels(code=status).inc()

        if response.status_code >= 500:
            app_errors_total.inc()

        # ── In-process live stats ─────────────────────────────
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
# BLOCK 8 — CORE FLASK ROUTES  ← COMPLETELY UNCHANGED
# ──────────────────────────────────────────────────────────────
# / → index.html        UNTOUCHED
# /health               UNTOUCHED
# /metrics              UNTOUCHED (Prometheus)
# /dashboard/agents     UNTOUCHED
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home():
    """
    Main UI — serves templates/index.html.
    THIS ROUTE IS UNTOUCHED.
    """
    return render_template("index.html")


@application.get("/health")
def health_check():
    """Liveness / readiness probe."""
    return Response("Healthy", status=200, content_type="text/plain")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """
    Prometheus scrape endpoint.
    THIS ROUTE IS UNTOUCHED.
    """
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@application.get("/dashboard/agents")
def agents_dashboard():
    """Agent dashboard alias — renders same index.html SPA."""
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════
# BLOCK 9 — AGENT MONITOR HTML ROUTES  (NEW)
# ──────────────────────────────────────────────────────────────
# All routes return colorful HTML via HTMLBuilder.
# Navigation buttons on every page link them all together.
# /metrics is taken by Prometheus so we use /monitor here.
# ══════════════════════════════════════════════════════════════

def _get_data():
    """Fetch files + metrics — used by every HTML page."""
    files = _db.execute(
        "SELECT * FROM detected_files "
        "ORDER BY is_ai_agent DESC, is_script DESC, "
        "is_main_file DESC, file_name",
        fetch=True
    )
    return [dict(f) for f in files], _monitor.get_all_metrics()


def _html(html_str):
    """Wrap string in Flask HTML Response."""
    return Response(
        html_str,
        status=200,
        content_type="text/html; charset=utf-8"
    )


# ── /dashboard ────────────────────────────────────────────────
@application.get("/dashboard")
def monitor_dashboard():
    """
    Full HTML dashboard — system resources, token/request usage.
    Auto-refreshes every 10 seconds.
    """
    files, metrics = _get_data()
    return _html(HTMLBuilder.dashboard(files, metrics))


# ── /files ────────────────────────────────────────────────────
@application.get("/files")
def files_page():
    """
    HTML page listing all detected project files with
    type, purpose, description, size and flags.
    """
    files, _ = _get_data()
    return _html(HTMLBuilder.files(files))


# ── /agents ───────────────────────────────────────────────────
@application.get("/agents")
def agents_page():
    """
    HTML page showing per-agent token, request and
    resource metrics. Auto-refreshes every 10 seconds.
    """
    files, metrics = _get_data()
    return _html(HTMLBuilder.agents(files, metrics))


# ── /monitor ──────────────────────────────────────────────────
# NOTE: Cannot use /metrics — that is Prometheus (BLOCK 8).
# Navigation bar shows this as "📈 Metrics" but route is /monitor.
@application.get("/monitor")
def monitor_page():
    """
    HTML page for token/request usage vs limits + cost estimate.
    Auto-refreshes every 10 seconds.
    """
    _, metrics = _get_data()
    return _html(HTMLBuilder.monitor(metrics))


# ── /model ────────────────────────────────────────────────────
@application.get("/model")
def model_page():
    """
    HTML page showing active model config, all providers,
    rate limits and pricing.
    """
    return _html(HTMLBuilder.model())


# ── /history ──────────────────────────────────────────────────
@application.get("/history")
def history_page():
    """
    HTML page showing last 50 scan history records.
    """
    return _html(HTMLBuilder.history(_db))


# ── /scan ─────────────────────────────────────────────────────
@application.get("/scan")
def scan_page():
    """
    Triggers a project scan then shows HTML result page
    with counts and links to dashboard / files.
    Optional query param: ?path=/your/project/path
    """
    sp      = request.args.get("path", SCAN_PATH)
    scanned = _scanner.scan_project(sp)
    result  = {
        "total": len(scanned),
        "ai":    sum(1 for f in scanned if f["is_ai_agent"]),
        "sc":    sum(1 for f in scanned if f["is_script"]),
        "mn":    sum(1 for f in scanned if f["is_main_file"]),
    }
    return _html(HTMLBuilder.scan_done(result))


# ── /reset ────────────────────────────────────────────────────
@application.get("/reset")
def reset_page():
    """
    Clears all DB tables and in-memory monitor state,
    then shows HTML confirmation page with nav buttons.
    """
    from collections import defaultdict

    _db.execute("DELETE FROM detected_files")
    _db.execute("DELETE FROM token_usage")
    _db.execute("DELETE FROM request_usage")
    _db.execute("DELETE FROM resource_usage")

    _monitor.metrics = {
        "tokens":    defaultdict(
            lambda: {"per_min": 0, "per_hour": 0, "per_day": 0}
        ),
        "requests":  defaultdict(
            lambda: {"per_min": 0, "per_hour": 0, "per_day": 0}
        ),
        "resources": {},
        "system":    {},
    }
    _monitor._tok_log.clear()
    _monitor._req_log.clear()

    return _html(HTMLBuilder.reset_done())


# ══════════════════════════════════════════════════════════════
# BLOCK 10 — AGENT MONITOR API ROUTES  (JSON)
# ──────────────────────────────────────────────────────────────
# These remain JSON for any frontend / external consumers.
# Unchanged from your original app.py — only the scanner
# source changed (now uses _db + _monitor instead of old scanner).
# ══════════════════════════════════════════════════════════════

# ── /api/metrics/system ──────────────────────────────────────
@application.route("/api/metrics/system", methods=["GET"])
def get_system_metrics():
    """System CPU, memory, disk metrics."""
    try:
        _, metrics = _get_data()
        return jsonify(metrics.get("system", {})), 200
    except Exception as e:
        application.logger.error(f"System metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/metrics/tokens ──────────────────────────────────────
@application.route("/api/metrics/tokens", methods=["GET"])
def get_token_metrics():
    """Token usage per file — per_min / per_hour / per_day."""
    try:
        _, metrics = _get_data()
        return jsonify(metrics.get("tokens", {})), 200
    except Exception as e:
        application.logger.error(f"Token metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/metrics/requests ────────────────────────────────────
@application.route("/api/metrics/requests", methods=["GET"])
def get_request_metrics():
    """Request rates rpm / rph / rpd plus timestamp."""
    try:
        _, metrics = _get_data()
        reqs = metrics.get("requests", {})
        rpm  = sum(v.get("per_min",  0) for v in reqs.values())
        rph  = sum(v.get("per_hour", 0) for v in reqs.values())
        rpd  = sum(v.get("per_day",  0) for v in reqs.values())
        return jsonify({
            "rpm": rpm, "rph": rph, "rpd": rpd,
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Request metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/agents ──────────────────────────────────────────────
@application.route("/api/agents", methods=["GET"])
def get_agents():
    """All detected AI agent files with count."""
    try:
        files, _ = _get_data()
        agents   = [f for f in files if f.get("is_ai_agent")]
        return jsonify({
            "agents":    agents,
            "count":     len(agents),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get agents error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/agents/<agent_id> ───────────────────────────────────
@application.route("/api/agents/<int:agent_id>", methods=["GET"])
def get_agent(agent_id):
    """Single agent by DB id, or 404."""
    try:
        row = _db.execute(
            "SELECT * FROM detected_files "
            "WHERE id=? AND is_ai_agent=1",
            (agent_id,), fetch=True
        )
        if row:
            return jsonify(dict(row[0])), 200
        return jsonify({"error": "Agent not found"}), 404
    except Exception as e:
        application.logger.error(f"Get agent error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/requests ────────────────────────────────────────────
@application.route("/api/requests", methods=["GET"])
def get_requests():
    """Recent request_usage rows, paginated by ?limit=."""
    try:
        limit = request.args.get("limit", 20, type=int)
        rows  = _db.execute(
            "SELECT * FROM request_usage "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,), fetch=True
        )
        scanned_requests = [dict(r) for r in rows]
        return jsonify({
            "requests":  scanned_requests,
            "count":     len(scanned_requests),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get requests error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/providers ───────────────────────────────────────────
@application.route("/api/providers", methods=["GET"])
def get_providers():
    """Provider list built from ACTIVE_CONFIG."""
    try:
        from agent_monitor import MODEL_REGISTRY
        providers = [
            {"name": p, "models": list(cfg["models"].keys())}
            for p, cfg in MODEL_REGISTRY.items()
        ]
        return jsonify({
            "providers": providers,
            "count":     len(providers),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get providers error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/report ──────────────────────────────────────────────
@application.route("/api/report", methods=["GET"])
def get_report():
    """Full snapshot — files + metrics + config."""
    try:
        files, metrics = _get_data()
        return jsonify({
            "report": {
                "files":         files,
                "system":        metrics.get("system",    {}),
                "tokens":        metrics.get("tokens",    {}),
                "requests":      metrics.get("requests",  {}),
                "resources":     metrics.get("resources", {}),
                "active_config": ACTIVE_CONFIG,
            },
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get report error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/status ──────────────────────────────────────────────
@application.route("/api/status", methods=["GET"])
def get_status():
    """
    Lightweight running summary — matches original JSON output:
    {"active_agents":0,"agents_count":0,"status":"running",
     "timestamp":...,"total_requests":0}
    """
    try:
        files, metrics = _get_data()
        ai_files = [f for f in files if f.get("is_ai_agent")]
        req_day  = sum(
            v.get("per_day", 0)
            for v in metrics.get("requests", {}).values()
        )
        return jsonify({
            "status":         "running",
            "agents_count":   len(ai_files),
            "active_agents":  len(ai_files),
            "total_requests": req_day,
            "total_files":    len(files),
            "timestamp":      time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get status error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/refresh  (POST) ─────────────────────────────────────
@application.route("/api/refresh", methods=["POST"])
def refresh_metrics():
    """Re-read metrics and return snapshot."""
    try:
        files, metrics = _get_data()
        ai_files = [f for f in files if f.get("is_ai_agent")]
        if not ai_files:
            return jsonify({"error": "No agents to refresh"}), 400
        return jsonify({
            "success":        True,
            "system_metrics": metrics.get("system",    {}),
            "token_metrics":  metrics.get("tokens",    {}),
            "req_metrics":    metrics.get("requests",  {}),
            "timestamp":      time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Refresh error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/clear  (POST) ───────────────────────────────────────
@application.route("/api/clear", methods=["POST"])
def clear_data():
    """
    Wipes all DB tables and in-memory monitor state.
    Same as /reset but returns JSON (for API consumers).
    """
    try:
        from collections import defaultdict
        with _SCANNER_LOCK:
            _db.execute("DELETE FROM detected_files")
            _db.execute("DELETE FROM token_usage")
            _db.execute("DELETE FROM request_usage")
            _db.execute("DELETE FROM resource_usage")
            _monitor.metrics = {
                "tokens":    defaultdict(
                    lambda: {"per_min": 0, "per_hour": 0, "per_day": 0}
                ),
                "requests":  defaultdict(
                    lambda: {"per_min": 0, "per_hour": 0, "per_day": 0}
                ),
                "resources": {},
                "system":    {},
            }
            _monitor._tok_log.clear()
            _monitor._req_log.clear()
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
# BLOCK 11 — ERROR HANDLERS
# ──────────────────────────────────────────────────────────────
# Unchanged from your original app.py.
# ══════════════════════════════════════════════════════════════

@application.errorhandler(Exception)
def handle_exception(e):
    """Catch-all for unhandled exceptions."""
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
    """404 handler."""
    return jsonify({"error": "Not found", "status": 404}), 404


# ══════════════════════════════════════════════════════════════
# BLOCK 12 — WSGI / __main__ ENTRY POINT
# ──────────────────────────────────────────────────────────────
# Unchanged from your original app.py.
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)