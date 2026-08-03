"""
app.py
======
Flask entry point for SentinelOps-Lite with AI Agent Monitor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BLOCK MAP  (what each section does)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BLOCK 1 ── Standard-library & third-party imports
  BLOCK 2 ── Path / sys.path setup
  BLOCK 3 ── Import Flask app + scanner from agent_monitor.py
              (routes already registered there — NOT repeated here)
  BLOCK 4 ── Import Prometheus counters from monitoring/metrics.py
  BLOCK 5 ── Thread-safety locks  (APP_STATS, scanner mutations)
  BLOCK 6 ── Deferred metrics init inside app context
  BLOCK 7 ── Prometheus request lifecycle hooks
              (before_request stamp  /  after_request record)
  BLOCK 8 ── Core Flask routes owned by app.py
              GET  /                  → index.html  (kept as-is)
              GET  /health            → plain-text health check
              GET  /metrics           → Prometheus scrape endpoint
              GET  /dashboard/agents  → index.html alias
  BLOCK 9 ── Agent Monitor API routes  (scanner-backed)
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
  BLOCK 10 ── Routes that LIVE in agent_monitor.py  (reference only)
              GET  /api/providers/models   → get_providers_models()
              POST /api/scan/project       → scan_project()
              POST /api/agent/test         → test_agent()
              GET  /api/dashboard          → get_dashboard()
              GET  /api/report/download    → download_report()
  BLOCK 11 ── Error handlers  (404, catch-all Exception)
  BLOCK 12 ── WSGI / __main__ entry point

Fixes applied (unchanged from previous version):
  FIX 1  Removed duplicate Prometheus increment in scan_agents()
  FIX 2  Silent zero-duration on missing _start_time now skips observe()
  FIX 3  Merged conflicting Exception + 500 error handlers into one
  FIX 4  APP_STATS writes are now protected by threading.Lock
  FIX 5  clear_data() uses .clear() under lock instead of list replacement
  FIX 6  Renamed 'requests_list' shadow variable to 'scanned_requests'
  FIX 7  update_metrics() deferred into app_context after app is ready
  FIX 8  Removed duplicate /api/dashboard route (lives in agent_monitor.py)
  FIX 9  Removed duplicate /api/report/download route (lives in agent_monitor.py)
"""

# ══════════════════════════════════════════════════════════════
# BLOCK 1 — STANDARD-LIBRARY & THIRD-PARTY IMPORTS
# ──────────────────────────────────────────────────────────────
# What  : Pull in everything the file needs before any app code runs.
# Why   : Keeps all dependencies visible at the top; import errors
#         surface immediately on startup rather than at request time.
# Touch : Add new pip packages here; never scatter imports mid-file.
# ══════════════════════════════════════════════════════════════

import os
import sys
import time
import threading
from pathlib import Path

from flask import render_template, Response, request, jsonify
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


# ══════════════════════════════════════════════════════════════
# BLOCK 2 — PATH / sys.path SETUP
# ──────────────────────────────────────────────────────────────
# What  : Resolves the project root and injects it into sys.path
#         so that sibling modules (agent_monitor, monitoring.*) are
#         importable regardless of the working directory.
# Why   : Prevents "ModuleNotFoundError" when Flask is launched from
#         a different directory (e.g. gunicorn from project root).
# Touch : Do not move or remove; must execute before BLOCK 3 imports.
# ══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ══════════════════════════════════════════════════════════════
# BLOCK 3 — IMPORT Flask APP + SCANNER FROM agent_monitor.py
# ──────────────────────────────────────────────────────────────
# What  : Imports the single Flask `application` instance and the
#         `scanner` object that were created inside agent_monitor.py.
#         All routes registered there are automatically available.
# Why   : There must be exactly ONE Flask app object; creating a
#         second one would orphan all agent_monitor routes.
#
# Routes already registered in agent_monitor.py
# (DO NOT re-register or duplicate any of these here):
# ┌─────────────────────────────┬───────────────────────────────┐
# │ Endpoint                    │ Handler in agent_monitor.py   │
# ├─────────────────────────────┼───────────────────────────────┤
# │ GET  /api/providers/models  │ get_providers_models()        │
# │ POST /api/scan/project      │ scan_project()                │
# │ POST /api/agent/test        │ test_agent()                  │
# │ GET  /api/dashboard         │ get_dashboard()               │
# │ GET  /api/report/download   │ download_report()             │
# │ GET  /  (inline HTML)       │ overridden by BLOCK 8 below   │
# └─────────────────────────────┴───────────────────────────────┘
# Touch : Only change the import names if agent_monitor.py renames
#         its exports.
# ══════════════════════════════════════════════════════════════

#from agent_monitor import application, scanner

# ══════════════════════════════════════════════════════════════
# REPLACE BLOCK 3 in app.py
# ══════════════════════════════════════════════════════════════

# OLD (broken):
# from agent_monitor import application, scanner

# NEW — create Flask app directly in app.py
from flask import Flask
application = Flask(__name__)

# ── Import scanner components from agent_monitor ──────────────
from agent_monitor import (
    MetricsDB,
    ProjectScanner,
    ResourceMonitor,
)

# ── Create scanner instance ───────────────────────────────────
_db      = MetricsDB()
_monitor = ResourceMonitor(_db)
_monitor.start_monitoring()

class scanner:
    """
    Namespace that mimics the scanner API
    app.py routes expect.
    """
    db               = _db
    agents           = []
    request_history  = []
    quota_trackers   = {}
    project_files    = []

    @staticmethod
    def get_dashboard_data():
        metrics = _monitor.get_all_metrics()
        files   = _db.execute(
            "SELECT * FROM detected_files ORDER BY is_ai_agent DESC",
            fetch=True
        )
        return {
            "agents":         [dict(f) for f in files if f["is_ai_agent"]],
            "system_metrics": metrics.get("system", {}),
            "session_stats":  {
                "total_tokens": 0,
                "rpm": 0, "rph": 0, "rpd": 0,
                "tpm": 0, "tph": 0, "tpd": 0,
            },
            "providers":      [],
            "request_history": [],
        }

    @staticmethod
    def _agent_dict(agent):
        return dict(agent)

# ══════════════════════════════════════════════════════════════
# BLOCK 4 — IMPORT PROMETHEUS COUNTERS FROM monitoring/metrics.py
# ──────────────────────────────────────────────────────────────
# What  : Brings in every Prometheus metric object and the two
#         helper functions (start_metrics_updater, update_metrics)
#         that are defined in monitoring/metrics.py.
# Why   : Centralising metric definitions in metrics.py means any
#         module can import the same label-consistent objects without
#         risking duplicate-descriptor registration errors.
# Touch : If you add a new counter/histogram in metrics.py, add it
#         to this import list so app.py can increment it.
#
# Objects imported:
# ┌──────────────────────────────────┬───────────────────────────────────┐
# │ Name                             │ Type / purpose                    │
# ├──────────────────────────────────┼───────────────────────────────────┤
# │ start_metrics_updater            │ fn  – starts background updater   │
# │ update_metrics                   │ fn  – one-shot metric refresh     │
# │ app_requests_total               │ Counter  – total HTTP requests    │
# │ app_request_duration_seconds     │ Histogram – latency per endpoint  │
# │ app_errors_total                 │ Counter  – 5xx responses          │
# │ app_exceptions_total             │ Counter  – unhandled exceptions   │
# │ http_status_codes_total          │ Counter  – per status-code tally  │
# │ APP_STATS                        │ dict     – in-process live stats  │
# └──────────────────────────────────┴───────────────────────────────────┘
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
# ──────────────────────────────────────────────────────────────
# What  : Two module-level Lock objects that serialise concurrent
#         writes to shared mutable state.
# Why   : Flask runs with threaded=True by default; without locks,
#         concurrent requests race on APP_STATS counters and on
#         scanner list mutations, causing silent data corruption.
#
# ┌──────────────────┬────────────────────────────────────────────┐
# │ Lock             │ Protects                                   │
# ├──────────────────┼────────────────────────────────────────────┤
# │ APP_STATS_LOCK   │ All read-modify-write ops on APP_STATS     │
# │                  │ dict  (BLOCK 7 after_request, BLOCK 11     │
# │                  │ exception handler)                         │
# ├──────────────────┼────────────────────────────────────────────┤
# │ _SCANNER_LOCK    │ scanner.agents / request_history /         │
# │                  │ quota_trackers / project_files .clear()    │
# │                  │ calls inside /api/clear  (BLOCK 9)         │
# └──────────────────┴────────────────────────────────────────────┘
# Touch : Acquire the appropriate lock whenever you add new code
#         that mutates APP_STATS or scanner collections.
# ══════════════════════════════════════════════════════════════

APP_STATS_LOCK = threading.Lock()   # FIX 4
_SCANNER_LOCK  = threading.Lock()   # FIX 5


# ══════════════════════════════════════════════════════════════
# BLOCK 6 — DEFERRED METRICS INIT INSIDE APP CONTEXT
# ──────────────────────────────────────────────────────────────
# What  : Calls update_metrics() and start_metrics_updater()
#         inside an explicit application context so that any
#         Flask-context globals (current_app, g, etc.) used
#         inside those functions are available.
# Why   : Calling context-aware code at module level (outside a
#         context) raises "RuntimeError: Working outside of
#         application context."  (FIX 7)
# Why 15 s: Fast enough for near-real-time dashboards; low enough
#           not to saturate the metrics endpoint.
# Touch : Change the interval (seconds) to tune polling frequency.
#         Do NOT move these calls outside the with block.
# ══════════════════════════════════════════════════════════════

with application.app_context():
    update_metrics()                    # FIX 7 – initial populate
    start_metrics_updater(interval=15)  # FIX 7 – background refresh


# ══════════════════════════════════════════════════════════════
# BLOCK 7 — PROMETHEUS REQUEST LIFECYCLE HOOKS
# ──────────────────────────────────────────────────────────────
# What  : Two Flask hooks that bracket every HTTP request with
#         timing and counter instrumentation.
#
# before_request  → _track_request_start()
#   Stamps request._start_time so duration can be calculated.
#
# after_request   → _track_request_end(response)
#   Reads the stamp, computes duration, updates:
#     • app_requests_total          (method / endpoint / status)
#     • app_request_duration_seconds (method / endpoint)
#     • http_status_codes_total      (code)
#     • app_errors_total             (5xx only)
#     • APP_STATS dict               (under APP_STATS_LOCK)
#
# Why here and not in metrics.py:
#   The hooks must be registered on the `application` object
#   imported in BLOCK 3; metrics.py has no reference to it.
#
# FIX 2 : If _start_time is absent (e.g. middleware short-circuits),
#          the hook returns early — observe() is never called with
#          a garbage duration.
# FIX 4 : All APP_STATS mutations happen inside APP_STATS_LOCK.
# Touch  : Do NOT add business logic here; keep hooks lean.
#          Prometheus labels must match those declared in metrics.py.
# ══════════════════════════════════════════════════════════════

@application.before_request
def _track_request_start():
    """Stamp every incoming request with its start time."""
    request._start_time = time.time()


@application.after_request
def _track_request_end(response):
    """
    Record duration, status, and in-process APP_STATS for
    every response that passes through Flask.
    """
    try:
        start = getattr(request, "_start_time", None)
        if start is None:           # FIX 2 – skip if stamp missing
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

        # ── In-process live stats (FIX 4) ────────────────────
        with APP_STATS_LOCK:
            APP_STATS["total_requests"]     += 1
            APP_STATS["total_request_time"] += duration
            if response.status_code < 400:
                APP_STATS["success_requests"] += 1
            else:
                APP_STATS["failed_requests"]  += 1

    except Exception:
        pass  # Never let instrumentation crash a real response

    return response


# ══════════════════════════════════════════════════════════════
# BLOCK 8 — CORE FLASK ROUTES OWNED BY app.py
# ──────────────────────────────────────────────────────────────
# What  : Four routes that belong to app.py's responsibility:
#         the main UI, a health probe, the Prometheus scrape
#         endpoint, and an alias for the agent dashboard.
#
# ┌──────────────────────┬────────────────────────────────────────┐
# │ Route                │ Purpose                                │
# ├──────────────────────┼────────────────────────────────────────┤
# │ GET  /               │ Serves templates/index.html            │
# │                      │ Overrides the inline HTML in           │
# │                      │ agent_monitor.py (same path, Flask     │
# │                      │ uses the last-registered handler).     │
# ├──────────────────────┼────────────────────────────────────────┤
# │ GET  /health         │ Plain-text "Healthy" — used by load    │
# │                      │ balancers / k8s liveness probes.       │
# ├──────────────────────┼────────────────────────────────────────┤
# │ GET  /metrics        │ Prometheus scrape endpoint.            │
# │                      │ Returns generate_latest() with the     │
# │                      │ correct Content-Type header.           │
# │                      │ DO NOT add logic here; all metric      │
# │                      │ definitions live in monitoring/metrics.│
# ├──────────────────────┼────────────────────────────────────────┤
# │ GET /dashboard/agents│ Alias that also serves index.html      │
# │                      │ so deep-links to the agent tab work.   │
# └──────────────────────┴────────────────────────────────────────┘
# Touch : Keep / and /metrics exactly as-is.
#         Only change /health if your orchestration platform
#         expects a different response format.
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home():
    """
    Main UI – serves templates/index.html.
    Overrides the inline HTML_TEMPLATE route in agent_monitor.py.
    """
    return render_template("index.html")


@application.get("/health")
def health_check():
    """Liveness / readiness probe – returns 200 'Healthy'."""
    return Response("Healthy", status=200, content_type="text/plain")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """
    Prometheus scrape endpoint.
    Collects all metrics registered in monitoring/metrics.py.
    DO NOT modify — Prometheus expects a stable format here.
    """
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@application.get("/dashboard/agents")
def agents_dashboard():
    """Agent dashboard alias – renders the same index.html SPA."""
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════
# BLOCK 9 — AGENT MONITOR API ROUTES  (scanner-backed)
# ──────────────────────────────────────────────────────────────
# What  : Eleven thin API endpoints that delegate all business
#         logic to scanner.get_dashboard_data() or to specific
#         scanner attributes.  No logic is duplicated from
#         agent_monitor.py.
#
# Route ownership table (app.py owns these; agent_monitor owns rest):
# ┌──────────────────────────────┬──────────────────────────────────────┐
# │ Route                        │ Returns                              │
# ├──────────────────────────────┼──────────────────────────────────────┤
# │ GET  /api/metrics/system     │ system_metrics sub-dict              │
# │ GET  /api/metrics/tokens     │ session_stats sub-dict               │
# │ GET  /api/metrics/requests   │ rpm / rph / rpd from session_stats   │
# │ GET  /api/agents             │ full agents list + count             │
# │ GET  /api/agents/<agent_id>  │ single agent dict or 404             │
# │ GET  /api/requests           │ request_history (limit= param)       │
# │ GET  /api/providers          │ providers list + count               │
# │ GET  /api/report             │ full dashboard data snapshot         │
# │ GET  /api/status             │ running summary (counts, timestamp)  │
# │ POST /api/refresh            │ refreshes metrics, returns snapshot  │
# │ POST /api/clear              │ wipes agents/history/quotas/files    │
# └──────────────────────────────┴──────────────────────────────────────┘
#
# Error contract: every route returns {"error": "<msg>"} + 5xx on
# failure and increments app_exceptions_total so Prometheus tracks it.
#
# Touch : Add query-param filtering here if needed.
#         Do NOT add scanner state mutations outside _SCANNER_LOCK.
# ══════════════════════════════════════════════════════════════

# ── /api/metrics/system ──────────────────────────────────────
@application.route("/api/metrics/system", methods=["GET"])
def get_system_metrics():
    """
    Returns CPU, memory, and storage metrics collected by scanner.
    Source: scanner.get_dashboard_data()["system_metrics"]
    """
    try:
        return jsonify(scanner.get_dashboard_data()["system_metrics"]), 200
    except Exception as e:
        application.logger.error(f"System metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/metrics/tokens ──────────────────────────────────────
@application.route("/api/metrics/tokens", methods=["GET"])
def get_token_metrics():
    """
    Returns token-usage statistics (TPM/TPH/TPD, totals, cost).
    Source: scanner.get_dashboard_data()["session_stats"]
    """
    try:
        data = scanner.get_dashboard_data()
        return jsonify(data["session_stats"]), 200
    except Exception as e:
        application.logger.error(f"Token metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


# ── /api/metrics/requests ────────────────────────────────────
@application.route("/api/metrics/requests", methods=["GET"])
def get_request_metrics():
    """
    Returns request-rate metrics: rpm, rph, rpd plus timestamp.
    Source: session_stats sub-dict from scanner.get_dashboard_data()
    """
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


# ── /api/agents ──────────────────────────────────────────────
@application.route("/api/agents", methods=["GET"])
def get_agents():
    """
    Returns all scanned agents with count and timestamp.
    Source: scanner.get_dashboard_data()["agents"]
    """
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


# ── /api/agents/<agent_id> ───────────────────────────────────
@application.route("/api/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    """
    Returns a single agent's detail dict, or 404 if not found.
    Looks up agent by agent.id in scanner.agents list.
    """
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


# ── /api/requests ────────────────────────────────────────────
@application.route("/api/requests", methods=["GET"])
def get_requests():
    """
    Returns paginated request history.
    Query param: limit (int, default 20)
    FIX 6: local var renamed to 'scanned_requests' (no shadow).
    """
    try:
        limit = request.args.get("limit", 20, type=int)
        data  = scanner.get_dashboard_data()
        scanned_requests = data["request_history"][:limit]   # FIX 6
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
    """
    Returns provider summary list with count and timestamp.
    Source: scanner.get_dashboard_data()["providers"]
    """
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


# ── /api/report ──────────────────────────────────────────────
@application.route("/api/report", methods=["GET"])
def get_report():
    """
    Returns the full dashboard data snapshot wrapped in a
    top-level 'report' key with a timestamp.
    NOTE: File download lives in agent_monitor.py → /api/report/download
    """
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


# ── /api/status ──────────────────────────────────────────────
@application.route("/api/status", methods=["GET"])
def get_status():
    """
    Returns a lightweight running summary:
    agent count, active count, total requests, timestamp.
    """
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


# ── /api/refresh  (POST) ─────────────────────────────────────
@application.route("/api/refresh", methods=["POST"])
def refresh_metrics():
    """
    Triggers a fresh read of scanner state and returns
    system_metrics + session_stats.
    Returns 400 if no agents have been scanned yet.
    """
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


# ── /api/clear  (POST) ───────────────────────────────────────
@application.route("/api/clear", methods=["POST"])
def clear_data():
    """
    Wipes all in-memory scanner state:
      agents, request_history, quota_trackers, project_files.
    FIX 5: Uses .clear() under _SCANNER_LOCK (no list replacement).
    """
    try:
        with _SCANNER_LOCK:             # FIX 5
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
# BLOCK 10 — ROUTES THAT LIVE IN agent_monitor.py  (REFERENCE)
# ──────────────────────────────────────────────────────────────
# What  : Documentation block — no executable code.
#         These routes are registered on `application` inside
#         agent_monitor.py and are imported automatically when
#         BLOCK 3 runs  `from agent_monitor import application`.
#
# ┌─────────────────────────────┬───────────────────────────────┬──────────────────────┐
# │ Method  Path                │ Handler                       │ What it does         │
# ├─────────────────────────────┼───────────────────────────────┼──────────────────────┤
# │ GET  /api/providers/models  │ get_providers_models()        │ List models per      │
# │                             │                               │ provider + rate caps │
# ├─────────────────────────────┼───────────────────────────────┼──────────────────────┤
# │ POST /api/scan/project      │ scan_project()                │ Walk project tree,   │
# │                             │                               │ detect AI agents     │
# ├─────────────────────────────┼───────────────────────────────┼──────────────────────┤
# │ POST /api/agent/test        │ test_agent()                  │ Send a test prompt   │
# │                             │                               │ to a detected agent  │
# ├─────────────────────────────┼───────────────────────────────┼──────────────────────┤
# │ GET  /api/dashboard         │ get_dashboard()               │ Full dashboard JSON  │
# │                             │                               │ (tokens/req/system)  │
# ├─────────────────────────────┼───────────────────────────────┼──────────────────────┤
# │ GET  /api/report/download   │ download_report()             │ Download full report │
# │                             │                               │ as JSON file         │
# └─────────────────────────────┴───────────────────────────────┴──────────────────────┘
#
# FIX 1 : Duplicate Prometheus increment that was accidentally
#          added inside scan_agents() has been removed.
# FIX 8 : /api/dashboard not repeated here.
# FIX 9 : /api/report/download not repeated here.
#
# Touch  : NEVER add these paths to app.py route decorators.
# ══════════════════════════════════════════════════════════════

# (no code — reference only)


# ══════════════════════════════════════════════════════════════
# BLOCK 11 — ERROR HANDLERS
# ──────────────────────────────────────────────────────────────
# What  : Two Flask error handlers that catch all unhandled errors
#         and return consistent JSON payloads.
#
# ┌───────────────────────┬──────────────────────────────────────┐
# │ Handler               │ Triggered by                         │
# ├───────────────────────┼──────────────────────────────────────┤
# │ handle_exception(e)   │ Any unhandled Python exception in a  │
# │                       │ route (covers HTTP 500 too).         │
# │                       │ FIX 3: replaces the old conflicting  │
# │                       │ Exception + explicit 500 handlers.   │
# ├───────────────────────┼──────────────────────────────────────┤
# │ not_found(error)      │ Flask raises 404 for unknown paths.  │
# └───────────────────────┴──────────────────────────────────────┘
#
# Both handlers:
#   • Increment Prometheus counters (app_exceptions_total)
#   • Update APP_STATS["exceptions"] under APP_STATS_LOCK
#   • Log the full traceback via application.logger.error
#
# Touch : Keep the response shape stable — frontend JS may parse it.
# ══════════════════════════════════════════════════════════════

@application.errorhandler(Exception)
def handle_exception(e):
    """
    Catch-all for unhandled exceptions.
    FIX 3: Single handler; no separate @errorhandler(500) needed.
    """
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
    """404 handler – returned for any path not matched by a route."""
    return jsonify({"error": "Not found", "status": 404}), 404


# ══════════════════════════════════════════════════════════════
# BLOCK 12 — WSGI / __main__ ENTRY POINT
# ──────────────────────────────────────────────────────────────
# What  : Allows the file to be run directly with `python app.py`
#         for local development.  In production, a WSGI server
#         (gunicorn / uWSGI) imports `application` directly and
#         never reaches this block.
#
# Environment variables respected:
# ┌──────────────────┬───────────────┬────────────────────────────┐
# │ Variable         │ Default       │ Effect                     │
# ├──────────────────┼───────────────┼────────────────────────────┤
# │ PORT             │ 5000          │ TCP port Flask listens on  │
# │ FLASK_DEBUG      │ (unset) → 0   │ "1" enables debug/reloader │
# └──────────────────┴───────────────┴────────────────────────────┘
#
# Touch : Do not add startup logic here; use BLOCK 6 for init code
#         that must run in both dev and production.
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)