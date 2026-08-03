"""
app.py
======
Flask entry point for SentinelOps-Lite with AI Agent Monitor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BLOCK MAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BLOCK 1  ── Standard-library & third-party imports
  BLOCK 2  ── Path / sys.path setup
  BLOCK 3  ── Flask app creation  (single instance)
  BLOCK 4  ── Import from agent_monitor.py  (classes only)
  BLOCK 5  ── Import Prometheus counters from monitoring/metrics.py
  BLOCK 6  ── Component initialisation  (DB / Scanner / Monitor)
  BLOCK 7  ── Thread-safety locks
  BLOCK 8  ── Deferred metrics init inside app context
  BLOCK 9  ── Prometheus request lifecycle hooks
  BLOCK 10 ── Core Flask routes  (UNCHANGED)
               GET  /                  → index.html
               GET  /health            → plain-text health check
               GET  /metrics           → Prometheus scrape endpoint
               GET  /dashboard/agents  → index.html alias
  BLOCK 11 ── Agent Monitor HTML routes
               GET  /dashboard         → HTMLBuilder.dashboard()
               GET  /files             → HTMLBuilder.files()
               GET  /agents            → HTMLBuilder.agents()
               GET  /monitor           → HTMLBuilder.monitor()
               GET  /model             → HTMLBuilder.model()
               GET  /history           → HTMLBuilder.history()
               GET  /scan              → HTMLBuilder.scan_done()
               GET  /reset             → HTMLBuilder.reset_done()
  BLOCK 12 ── Agent Monitor API routes  (JSON)
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
  BLOCK 13 ── Error handlers
  BLOCK 14 ── WSGI / __main__ entry point
"""

# ══════════════════════════════════════════════════════════════
# BLOCK 1 — STANDARD-LIBRARY & THIRD-PARTY IMPORTS
# ══════════════════════════════════════════════════════════════

import os
import sys
import time
import threading
from collections import defaultdict
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
# BLOCK 3 — FLASK APP CREATION
# ──────────────────────────────────────────────────────────────
# Single instance created here — never duplicated.
# ══════════════════════════════════════════════════════════════

application = Flask(__name__)


# ══════════════════════════════════════════════════════════════
# BLOCK 4 — IMPORT FROM agent_monitor.py
# ──────────────────────────────────────────────────────────────
# agent_monitor.py = pure classes, no Flask, no HTTP server.
# All exports verified from the file provided.
# ══════════════════════════════════════════════════════════════

try:
    from agent_monitor import (
        MetricsDB,
        ProjectScanner,
        ResourceMonitor,
        HTMLBuilder,
        ACTIVE_CONFIG,
        MODEL_REGISTRY,
        ACTIVE_PROVIDER,
        ACTIVE_MODEL,
        AI_PROVIDER,
        AI_MODEL,
    )
    print("[app] ✅ agent_monitor imported OK")
except ImportError as e:
    print(f"[app] ❌ agent_monitor import FAILED: {e}")
    raise


# ══════════════════════════════════════════════════════════════
# BLOCK 5 — IMPORT PROMETHEUS COUNTERS
# ══════════════════════════════════════════════════════════════

try:
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
    print("[app] ✅ monitoring.metrics imported OK")
except ImportError as e:
    print(f"[app] ❌ monitoring.metrics import FAILED: {e}")
    raise


# ══════════════════════════════════════════════════════════════
# BLOCK 6 — COMPONENT INITIALISATION
# ──────────────────────────────────────────────────────────────
# Import order:
#   BLOCK 3 (Flask app) → BLOCK 4 (agent_monitor) →
#   BLOCK 5 (metrics)   → BLOCK 6 (init components)
#
# SCAN_PATH priority:
#   1. SCAN_PATH env var  (explicit override)
#   2. /var/app/current   (AWS Beanstalk standard)
#   3. BASE_DIR           (local dev fallback)
# ══════════════════════════════════════════════════════════════

_BEANSTALK_PATH = "/var/app/current"
SCAN_PATH = os.environ.get(
    "SCAN_PATH",
    _BEANSTALK_PATH if os.path.exists(_BEANSTALK_PATH) else str(BASE_DIR)
)
print(f"[app] 📁 SCAN_PATH = {SCAN_PATH}")

# ── Database ──────────────────────────────────────────────────
try:
    _db = MetricsDB()
    print("[app] ✅ MetricsDB ready")
except Exception as e:
    print(f"[app] ❌ MetricsDB FAILED: {e}")
    raise

# ── Scanner ───────────────────────────────────────────────────
try:
    _scanner = ProjectScanner(_db)
    print("[app] ✅ ProjectScanner ready")
except Exception as e:
    print(f"[app] ❌ ProjectScanner FAILED: {e}")
    raise

# ── Resource monitor ──────────────────────────────────────────
try:
    _monitor = ResourceMonitor(_db)
    _monitor.start_monitoring()
    print("[app] ✅ ResourceMonitor started")
except Exception as e:
    print(f"[app] ❌ ResourceMonitor FAILED: {e}")
    raise

# ── Initial scan (non-fatal) ──────────────────────────────────
try:
    _files = _scanner.scan_project(SCAN_PATH)
    _ai = sum(1 for f in _files if f['is_ai_agent'])
    _sc = sum(1 for f in _files if f['is_script'])
    _mn = sum(1 for f in _files if f['is_main_file'])
    print(
        f"[app] ✅ Scan done — "
        f"{len(_files)} files | {_ai} AI | {_sc} scripts | {_mn} main"
    )
except Exception as e:
    print(f"[app] ⚠ Initial scan error (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════
# BLOCK 7 — THREAD-SAFETY LOCKS
# ══════════════════════════════════════════════════════════════

APP_STATS_LOCK = threading.Lock()
_SCANNER_LOCK  = threading.Lock()


# ══════════════════════════════════════════════════════════════
# BLOCK 8 — DEFERRED METRICS INIT INSIDE APP CONTEXT
# ──────────────────────────────────────────────────────────────
# Must run after BLOCK 3 (app exists) and BLOCK 5 (metrics imported).
# Non-fatal so app still starts if Prometheus init fails.
# ══════════════════════════════════════════════════════════════

try:
    with application.app_context():
        update_metrics()
        start_metrics_updater(interval=15)
    print("[app] ✅ Prometheus metrics updater started")
except Exception as e:
    print(f"[app] ⚠ Metrics updater error (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════
# BLOCK 9 — PROMETHEUS REQUEST LIFECYCLE HOOKS
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
# BLOCK 10 — CORE FLASK ROUTES  (COMPLETELY UNCHANGED)
# ──────────────────────────────────────────────────────────────
# These 4 routes are exactly as they were originally.
# DO NOT modify them.
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home():
    """Main UI — serves templates/index.html. UNTOUCHED."""
    return render_template("index.html")


@application.get("/health")
def health_check():
    """Liveness / readiness probe for load balancers."""
    return Response("Healthy", status=200, content_type="text/plain")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """Prometheus scrape endpoint. UNTOUCHED."""
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@application.get("/dashboard/agents")
def agents_dashboard():
    """Agent dashboard alias — renders same index.html SPA."""
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════
# BLOCK 11 — AGENT MONITOR HTML ROUTES
# ──────────────────────────────────────────────────────────────
# All return colorful HTML via HTMLBuilder static methods.
# Every page has a nav bar linking all pages together.
# /metrics is taken by Prometheus — we use /monitor instead.
# ══════════════════════════════════════════════════════════════

def _get_data():
    """
    Fetch files + metrics from DB and monitor.
    Used by every HTML route and JSON API route.
    """
    rows = _db.execute(
        "SELECT * FROM detected_files "
        "ORDER BY is_ai_agent DESC, is_script DESC, "
        "is_main_file DESC, file_name",
        fetch=True
    )
    files   = [dict(r) for r in rows]
    metrics = _monitor.get_all_metrics()
    return files, metrics


def _html(html_str):
    """Return a Flask HTML Response from a string."""
    return Response(
        html_str,
        status=200,
        content_type="text/html; charset=utf-8"
    )


@application.get("/dashboard")
def monitor_dashboard():
    """
    Full overview — files, system resources, token/request usage.
    Auto-refreshes every 10 seconds.
    """
    files, metrics = _get_data()
    return _html(HTMLBuilder.dashboard(files, metrics))


@application.get("/files")
def files_page():
    """All detected project files — type, purpose, description, size."""
    files, _ = _get_data()
    return _html(HTMLBuilder.files(files))


@application.get("/agents")
def agents_page():
    """
    Per-agent token, request and resource metrics.
    Auto-refreshes every 10 seconds.
    """
    files, metrics = _get_data()
    return _html(HTMLBuilder.agents(files, metrics))


@application.get("/monitor")
def monitor_page():
    """
    Token/request usage vs limits + estimated cost.
    Auto-refreshes every 10 seconds.
    NOTE: route is /monitor because /metrics is Prometheus.
    """
    _, metrics = _get_data()
    return _html(HTMLBuilder.monitor(metrics))


@application.get("/model")
def model_page():
    """Active model config, rate limits, pricing, all providers."""
    return _html(HTMLBuilder.model())


@application.get("/history")
def history_page():
    """Last 50 scan history records."""
    return _html(HTMLBuilder.history(_db))


@application.get("/scan")
def scan_page():
    """
    Triggers a fresh project scan then shows result page.
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


@application.get("/reset")
def reset_page():
    """Clears all DB tables + in-memory monitor state → shows confirmation."""
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
# BLOCK 12 — AGENT MONITOR API ROUTES  (JSON)
# ══════════════════════════════════════════════════════════════

@application.route("/api/metrics/system", methods=["GET"])
def get_system_metrics():
    """System CPU, memory, disk metrics as JSON."""
    try:
        _, metrics = _get_data()
        return jsonify(metrics.get("system", {})), 200
    except Exception as e:
        application.logger.error(f"System metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


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


@application.route("/api/metrics/requests", methods=["GET"])
def get_request_metrics():
    """Aggregated request rates — rpm / rph / rpd."""
    try:
        _, metrics = _get_data()
        reqs = metrics.get("requests", {})
        return jsonify({
            "rpm":       sum(v.get("per_min",  0) for v in reqs.values()),
            "rph":       sum(v.get("per_hour", 0) for v in reqs.values()),
            "rpd":       sum(v.get("per_day",  0) for v in reqs.values()),
            "timestamp": time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Request metrics error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


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


@application.route("/api/agents/<int:agent_id>", methods=["GET"])
def get_agent(agent_id):
    """Single agent by DB id, or 404."""
    try:
        row = _db.execute(
            "SELECT * FROM detected_files WHERE id=? AND is_ai_agent=1",
            (agent_id,), fetch=True
        )
        if row:
            return jsonify(dict(row[0])), 200
        return jsonify({"error": "Agent not found"}), 404
    except Exception as e:
        application.logger.error(f"Get agent error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


@application.route("/api/requests", methods=["GET"])
def get_requests():
    """Recent request_usage rows, paginated by ?limit=."""
    try:
        limit            = request.args.get("limit", 20, type=int)
        rows             = _db.execute(
            "SELECT * FROM request_usage ORDER BY timestamp DESC LIMIT ?",
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


@application.route("/api/providers", methods=["GET"])
def get_providers():
    """All providers and their models from MODEL_REGISTRY."""
    try:
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


@application.route("/api/report", methods=["GET"])
def get_report():
    """Full snapshot — files + metrics + active config."""
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


@application.route("/api/status", methods=["GET"])
def get_status():
    """
    Lightweight running summary.
    Matches original JSON shape:
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


@application.route("/api/refresh", methods=["POST"])
def refresh_metrics():
    """Re-read metrics and return current snapshot."""
    try:
        files, metrics = _get_data()
        ai_files       = [f for f in files if f.get("is_ai_agent")]
        return jsonify({
            "success":        True,
            "agents_found":   len(ai_files),
            "system_metrics": metrics.get("system",   {}),
            "token_metrics":  metrics.get("tokens",   {}),
            "req_metrics":    metrics.get("requests", {}),
            "timestamp":      time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Refresh error: {e}")
        app_exceptions_total.inc()
        return jsonify({"error": str(e)}), 500


@application.route("/api/clear", methods=["POST"])
def clear_data():
    """
    Wipes all DB tables and in-memory monitor state.
    JSON version of /reset — for API consumers.
    """
    try:
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
# BLOCK 13 — ERROR HANDLERS
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
    """404 — path not matched by any route."""
    return jsonify({"error": "Not found", "status": 404}), 404


# ══════════════════════════════════════════════════════════════
# BLOCK 14 — WSGI / __main__ ENTRY POINT
# ──────────────────────────────────────────────────────────────
# Production: gunicorn imports `application` directly.
# Local dev:  python app.py
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)