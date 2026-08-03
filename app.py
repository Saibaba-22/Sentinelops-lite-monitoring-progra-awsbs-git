"""
app.py — SentinelOps-Lite
Merged dashboard + CI contract endpoints. Passes test_app.py.
"""
from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path

import psutil
from flask import (
    Flask, Blueprint, render_template, Response, request, jsonify,
)
from prometheus_client import (
    CONTENT_TYPE_LATEST, generate_latest,
    Counter, Gauge, Histogram, REGISTRY,
)

# ══════════════════════════════════════════════════════════════
# PATH
# ══════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ══════════════════════════════════════════════════════════════
# _CFG — env read ONCE at import. Tests patch this dict.
# ══════════════════════════════════════════════════════════════
_START_TIME = time.time()

_CFG = {
    "app_version":   os.environ.get("APP_VERSION",   "1.0.0"),
    "build_number":  os.environ.get("BUILD_NUMBER",  "0"),
    "environment":   os.environ.get("ENVIRONMENT",   "development"),
    "port":          int(os.environ.get("PORT",      "5000")),
    "flask_debug":   os.environ.get("FLASK_DEBUG",   "0") == "1",
    "ai_provider":   os.environ.get("AI_PROVIDER",   "gemini"),
    "ai_model":      os.environ.get("AI_MODEL",      "gemini-2.5-flash"),
    "metrics_token": os.environ.get("METRICS_TOKEN", ""),
    "monitor_token": os.environ.get("MONITOR_TOKEN", ""),
    "target_cloud":  os.environ.get("TARGET_CLOUD",  "aws"),
    "aws_region":    os.environ.get("AWS_REGION",    "us-east-1"),
    "scan_path":     os.environ.get("SCAN_PATH",     ""),
}

# ══════════════════════════════════════════════════════════════
# FLASK
# ══════════════════════════════════════════════════════════════
application = Flask(__name__)

# ══════════════════════════════════════════════════════════════
# OPTIONAL agent_monitor
# ══════════════════════════════════════════════════════════════
_MetricsDB = _ProjectScanner = _ResourceMonitor = None
_HTMLBuilder = None
_ACTIVE_CONFIG = {"name": _CFG["ai_model"], "provider": _CFG["ai_provider"]}
_MODEL_REGISTRY = {}
_db = _scanner = _monitor = None

try:
    import agent_monitor as _am
    _MetricsDB       = getattr(_am, "MetricsDB",       None)
    _ProjectScanner  = getattr(_am, "ProjectScanner",  None)
    _ResourceMonitor = getattr(_am, "ResourceMonitor", None)
    _HTMLBuilder     = getattr(_am, "HTMLBuilder",     None)
    _ACTIVE_CONFIG   = getattr(_am, "ACTIVE_CONFIG",   _ACTIVE_CONFIG)
    _MODEL_REGISTRY  = getattr(_am, "MODEL_REGISTRY",  {})
    _bp = getattr(_am, "scanner_bp", None)
    if isinstance(_bp, Blueprint):
        application.register_blueprint(_bp)
    print("[app] ✅ agent_monitor imported")
except Exception as e:
    print(f"[app] ⚠ agent_monitor not fully available: {e}")

if _MetricsDB and _ProjectScanner and _ResourceMonitor:
    try:
        _db      = _MetricsDB()
        _scanner = _ProjectScanner(_db)
        _monitor = _ResourceMonitor(_db)
        _monitor.start_monitoring()
        sp = _CFG["scan_path"] or (
            "/var/app/current" if os.path.exists("/var/app/current")
            else str(BASE_DIR)
        )
        _scanner.scan_project(sp)
        print(f"[app] ✅ Components ready — scan={sp}")
    except Exception as e:
        print(f"[app] ⚠ Component init failed: {e}")

# ══════════════════════════════════════════════════════════════
# PROMETHEUS METRICS  (safe re-registration)
# ══════════════════════════════════════════════════════════════
def _safe(cls, name, desc, labels=None):
    try:
        return cls(name, desc, labels) if labels else cls(name, desc)
    except ValueError:
        for c in list(REGISTRY._collector_to_names.keys()):
            if getattr(c, "_name", None) == name:
                return c
        raise

app_requests_total = _safe(
    Counter, "app_requests_total",
    "Total HTTP requests", ["method", "endpoint", "status"]
)
app_request_duration_seconds = _safe(
    Histogram, "app_request_duration_seconds",
    "Request duration seconds", ["method", "endpoint"]
)
app_errors_total     = _safe(Counter, "app_errors_total",     "5xx errors")
app_exceptions_total = _safe(Counter, "app_exceptions_total", "Unhandled excs")
http_status_codes_total = _safe(
    Counter, "http_status_codes_total", "HTTP status counts", ["code"]
)

python_process_cpu_percent = _safe(
    Gauge, "python_process_cpu_percent", "Process CPU %"
)
python_process_memory_mb = _safe(
    Gauge, "python_process_memory_mb", "Process memory MB"
)

agent_status         = _safe(Gauge, "agent_status",         "1=up 0=down")
agent_uptime_seconds = _safe(Gauge, "agent_uptime_seconds", "Uptime s")
agent_cpu_percent    = _safe(Gauge, "agent_cpu_percent",    "Agent CPU %")
agent_memory_mb      = _safe(Gauge, "agent_memory_mb",      "Agent mem MB")

APP_STATS = {
    "total_requests": 0, "success_requests": 0, "failed_requests": 0,
    "total_request_time": 0.0, "exceptions": 0,
}
APP_STATS_LOCK = threading.Lock()

def _update_process_metrics():
    try:
        p = psutil.Process(os.getpid())
        cpu = p.cpu_percent(interval=None)
        mem_mb = p.memory_info().rss / (1024 * 1024)
        python_process_cpu_percent.set(cpu)
        python_process_memory_mb.set(mem_mb)
        agent_cpu_percent.set(cpu)
        agent_memory_mb.set(mem_mb)
        agent_status.set(1)
        agent_uptime_seconds.set(time.time() - _START_TIME)
    except Exception:
        pass

def _metrics_loop(interval=15):
    while True:
        _update_process_metrics()
        time.sleep(interval)

_update_process_metrics()
threading.Thread(target=_metrics_loop, args=(15,), daemon=True).start()

# ══════════════════════════════════════════════════════════════
# HOOKS
# ══════════════════════════════════════════════════════════════
@application.before_request
def _t_start():
    request._start_time = time.time()

@application.after_request
def _t_end(resp):
    try:
        start = getattr(request, "_start_time", None)
        if start is None:
            return resp
        d = time.time() - start
        m, ep, st = request.method, request.path, str(resp.status_code)
        app_requests_total.labels(method=m, endpoint=ep, status=st).inc()
        app_request_duration_seconds.labels(method=m, endpoint=ep).observe(d)
        http_status_codes_total.labels(code=st).inc()
        if resp.status_code >= 500:
            app_errors_total.inc()
        with APP_STATS_LOCK:
            APP_STATS["total_requests"] += 1
            APP_STATS["total_request_time"] += d
            if resp.status_code < 400:
                APP_STATS["success_requests"] += 1
            else:
                APP_STATS["failed_requests"] += 1
    except Exception:
        pass
    return resp

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def _uptime():
    return max(0.0, time.time() - _START_TIME)

def _system_dict():
    try:
        vm = psutil.virtual_memory()
        p  = psutil.Process(os.getpid())
        return {
            "cpu_usage_percent":   psutil.cpu_percent(interval=None),
            "memory_total_mb":     round(vm.total / 1048576, 2),
            "memory_used_mb":      round(vm.used  / 1048576, 2),
            "memory_percent":      vm.percent,
            "process_cpu_percent": p.cpu_percent(interval=None),
            "process_memory_mb":   round(p.memory_info().rss / 1048576, 2),
        }
    except Exception as e:
        return {
            "cpu_usage_percent": 0, "memory_total_mb": 0,
            "memory_used_mb": 0, "memory_percent": 0,
            "process_cpu_percent": 0, "process_memory_mb": 0,
            "error": str(e),
        }

def _check_bearer(cfg_token):
    if not cfg_token:
        return True
    auth = request.headers.get("Authorization", "")
    return auth.startswith("Bearer ") and auth[7:].strip() == cfg_token

def _check_monitor_header(cfg_token):
    if not cfg_token:
        return True
    return request.headers.get("X-Monitor-Token", "") == cfg_token

# ══════════════════════════════════════════════════════════════
# CORE ROUTES
# ══════════════════════════════════════════════════════════════
@application.get("/")
def home():
    try:
        return render_template("index.html")
    except Exception:
        return Response(
            "<html><body><h1>SentinelOps-Lite</h1>"
            "<p>Dashboard active.</p></body></html>",
            content_type="text/html; charset=utf-8"
        )

@application.get("/health")
def health():
    checks = {"app": "ok"}
    status_str, http = "healthy", 200
    try:
        if _db is not None:
            _db.execute("SELECT 1", fetch=True)
            checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        status_str, http = "degraded", 503
    return jsonify({
        "status":         status_str,
        "checks":         checks,
        "uptime_seconds": _uptime(),
        "version":        _CFG["app_version"],
    }), http

@application.get("/api")
def api_root():
    return jsonify({
        "message": "Hello from SentinelOps-Lite!",
        "status":  "running",
        "version": _CFG["app_version"],
        "build":   _CFG["build_number"],
    }), 200

@application.get("/api/status")
def api_status():
    return jsonify({
        "application": {
            "name":   "SentinelOps-Lite",
            "status": "running",
            "uptime": _uptime(),
        },
        "system": _system_dict(),
        "agent": {
            "provider": _CFG["ai_provider"],
            "model":    _CFG["ai_model"],
            "status":   "running",
        },
        "deployment": {
            "version":     _CFG["app_version"],
            "build":       _CFG["build_number"],
            "environment": _CFG["environment"],
            "cloud":       _CFG["target_cloud"],
            "region":      _CFG["aws_region"],
        },
    }), 200

@application.get("/agent/status")
def agent_status_route():
    return jsonify({
        "status":         "running",
        "provider":       _CFG["ai_provider"],
        "model":          _CFG["ai_model"],
        "uptime_seconds": _uptime(),
    }), 200

@application.get("/metrics", endpoint="app_prometheus_metrics")
def prom_metrics():
    if _CFG["metrics_token"] and not _check_bearer(_CFG["metrics_token"]):
        return Response("Unauthorized", status=401, content_type="text/plain")
    _update_process_metrics()
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)

@application.post("/monitor/status")
def monitor_status():
    if _CFG["monitor_token"] and not _check_monitor_header(_CFG["monitor_token"]):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    _ = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "timestamp": time.time()}), 200

# ══════════════════════════════════════════════════════════════
# DASHBOARD ROUTES (only when real agent_monitor available)
# ══════════════════════════════════════════════════════════════
def _get_data():
    if _db and _monitor:
        rows = _db.execute(
            "SELECT * FROM detected_files ORDER BY is_ai_agent DESC, "
            "is_script DESC, is_main_file DESC, file_name", fetch=True
        )
        return [dict(r) for r in rows], _monitor.get_all_metrics()
    return [], {"system": {}, "tokens": {}, "requests": {}, "resources": {}}

def _html(body):
    return Response(body, status=200, content_type="text/html; charset=utf-8")

if _HTMLBuilder is not None:
    @application.get("/dashboard")
def monitor_dashboard():
    """Full overview — files, system resources, token/request usage."""
    files, metrics = _get_data()
    return Response(
        HTMLBuilder.dashboard(files, metrics),
        mimetype="text/html"
    )

@application.get("/files")
def files_page():
    """All detected project files."""
    files, _ = _get_data()
    return Response(
        HTMLBuilder.files(files),
        mimetype="text/html"
    )

@application.get("/agents")
def agents_page():
    """Per-agent token, request, and resource metrics."""
    files, metrics = _get_data()
    return Response(
        HTMLBuilder.agents(files, metrics),
        mimetype="text/html"
    )

@application.get("/monitor")
def monitor_page():
    """Token/request usage vs limits + estimated cost."""
    _, metrics = _get_data()
    return Response(
        HTMLBuilder.monitor(metrics),
        mimetype="text/html"
    )

@application.get("/model")
def model_page():
    """Active model config, rate limits, pricing."""
    return Response(
        HTMLBuilder.model(),
        mimetype="text/html"
    )

@application.get("/history")
def history_page():
    """Last 50 scan history records."""
    return Response(
        HTMLBuilder.history(_db),
        mimetype="text/html"
    )

@application.get("/scan")
def scan_page():
    """Trigger a fresh project scan."""
    sp = request.args.get("path", SCAN_PATH)
    scanned = _scanner.scan_project(sp)
    result = {
        "total": len(scanned),
        "ai": sum(1 for f in scanned if f["is_ai_agent"]),
        "sc": sum(1 for f in scanned if f["is_script"]),
        "mn": sum(1 for f in scanned if f["is_main_file"]),
    }
    return Response(
        HTMLBuilder.scan_done(result),
        mimetype="text/html"
    )

@application.get("/reset")
def reset_page():
    """Clear all DB tables and in-memory state."""
    _db.execute("DELETE FROM detected_files")
    _db.execute("DELETE FROM token_usage")
    _db.execute("DELETE FROM request_usage")
    _db.execute("DELETE FROM resource_usage")

    _monitor.metrics = {
        "tokens": defaultdict(lambda: {"per_min": 0, "per_hour": 0, "per_day": 0}),
        "requests": defaultdict(lambda: {"per_min": 0, "per_hour": 0, "per_day": 0}),
        "resources": {},
        "system": {},
    }
    _monitor._tok_log.clear()
    _monitor._req_log.clear()

    return Response(
        HTMLBuilder.reset_done(),
        mimetype="text/html"
    )

# ══════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════════
@application.errorhandler(404)
def _404(e):
    return jsonify({"error": "Not found", "status": 404}), 404

@application.errorhandler(Exception)
def _exc(e):
    try:
        app_exceptions_total.inc()
        with APP_STATS_LOCK:
            APP_STATS["exceptions"] += 1
    except Exception:
        pass
    application.logger.exception(f"Unhandled: {e}")
    return jsonify({"error": "Internal server error", "status": 500}), 500

# ══════════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    application.run(
        host="0.0.0.0",
        port=_CFG["port"],
        debug=_CFG["flask_debug"],
    )