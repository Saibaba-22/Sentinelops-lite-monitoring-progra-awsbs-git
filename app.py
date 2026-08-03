"""app.py — SentinelOps-Lite"""
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
# PATHS + DB LOCATION
# ══════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Force absolute DB path so all workers/threads share the same file
os.environ.setdefault("METRICS_DB_PATH", "/tmp/agent_monitor.db")

_START_TIME = time.time()
_IMPORT_ERROR = None

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
    "db_path":       os.environ.get("METRICS_DB_PATH", "/tmp/agent_monitor.db"),
}

application = Flask(__name__)

# ══════════════════════════════════════════════════════════════
# IMPORT agent_monitor
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
    print("[app] agent_monitor imported")
except Exception as e:
    _IMPORT_ERROR = f"{type(e).__name__}: {e}"
    print(f"[app] agent_monitor not fully available: {_IMPORT_ERROR}")


def _init_components():
    """Called on startup AND lazily if worker has None components."""
    global _db, _scanner, _monitor
    if not (_MetricsDB and _ProjectScanner and _ResourceMonitor):
        return False
    try:
        # Force absolute DB path so every worker shares the same file
        try:
            _db = _MetricsDB(db_path=_CFG["db_path"])
        except TypeError:
            # Older MetricsDB signature — patch afterwards
            _db = _MetricsDB()
            _db.db_path = _CFG["db_path"]
        _scanner = _ProjectScanner(_db)
        _monitor = _ResourceMonitor(_db)
        _monitor.start_monitoring()
        target = _CFG["scan_path"] or (
            "/var/app/current" if os.path.exists("/var/app/current")
            else str(BASE_DIR)
        )
        _scanner.scan_project(target)
        print(f"[app] components ready pid={os.getpid()} "
              f"db={_db.db_path} scan={target}")
        return True
    except Exception as e:
        print(f"[app] component init failed: {e}")
        return False


_init_components()

# ══════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
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
app_errors_total = _safe(Counter, "app_errors_total", "5xx errors")
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
agent_status = _safe(Gauge, "agent_status", "1=up 0=down")
agent_uptime_seconds = _safe(Gauge, "agent_uptime_seconds", "Uptime s")
agent_cpu_percent = _safe(Gauge, "agent_cpu_percent", "Agent CPU %")
agent_memory_mb = _safe(Gauge, "agent_memory_mb", "Agent mem MB")

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
# REQUEST HOOKS
# ══════════════════════════════════════════════════════════════
@application.before_request
def _t_start():
    request._start_time = time.time()
    # Lazy init: if this worker has no components yet, init them
    if _db is None or _scanner is None or _monitor is None:
        if _MetricsDB and _ProjectScanner and _ResourceMonitor:
            _init_components()


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
        p = psutil.Process(os.getpid())
        return {
            "cpu_usage_percent":   psutil.cpu_percent(interval=None),
            "memory_total_mb":     round(vm.total / 1048576, 2),
            "memory_used_mb":      round(vm.used / 1048576, 2),
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
            "<html><body><h1>SentinelOps-Lite</h1></body></html>",
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
            "name": "SentinelOps-Lite",
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


# ══════════════════════════════════════════════════════════════
# DEBUG ROUTES
# ══════════════════════════════════════════════════════════════
@application.get("/debug")
def debug_page():
    import traceback
    info = {
        "pid":           os.getpid(),
        "_db":           str(_db),
        "_db_path":      _db.db_path if _db else None,
        "_scanner":      str(_scanner),
        "_monitor":      str(_monitor),
        "_HTMLBuilder":  str(_HTMLBuilder),
        "_IMPORT_ERROR": _IMPORT_ERROR,
        "BASE_DIR":      str(BASE_DIR),
        "SCAN_PATH":     _CFG["scan_path"],
        "cwd":           os.getcwd(),
        "AI_MODEL":      _CFG["ai_model"],
        "AI_PROVIDER":   _CFG["ai_provider"],
    }
    try:
        if _db:
            rows = _db.execute(
                "SELECT COUNT(*) as c FROM detected_files", fetch=True
            )
            info["db_file_count"] = dict(rows[0])["c"] if rows else 0
    except Exception as e:
        info["db_error"] = str(e)
    try:
        info["files_in_base"] = os.listdir(str(BASE_DIR))[:30]
    except Exception as e:
        info["files_in_base_error"] = str(e)
    return jsonify(info), 200


@application.get("/debug2")
def debug2():
    try:
        rows = _db.execute(
            "SELECT * FROM detected_files LIMIT 5", fetch=True
        )
        return jsonify({
            "pid":    os.getpid(),
            "count":  len(rows) if rows else 0,
            "sample": [dict(r) for r in (rows or [])],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@application.get("/debug3")
def debug3():
    """Return exactly what _get_data() gives to the dashboard."""
    try:
        files, metrics = _get_data()
        return jsonify({
            "pid":          os.getpid(),
            "files_count":  len(files),
            "files_sample": files[:3],
            "system":       metrics.get("system", {}),
            "tokens_keys":  list(metrics.get("tokens", {}).keys())[:5],
            "req_keys":     list(metrics.get("requests", {}).keys())[:5],
        })
    except Exception as e:
        import traceback
        return jsonify(
            {"error": str(e), "traceback": traceback.format_exc()}
        ), 500


@application.get("/debug4")
def debug4():
    return jsonify({
        "pid":         os.getpid(),
        "db_id":       id(_db) if _db else None,
        "db_path":     _db.db_path if _db else None,
        "scanner_id":  id(_scanner) if _scanner else None,
        "monitor_id":  id(_monitor) if _monitor else None,
    })

@application.get("/debug5")
def debug5():
    """Test the exact SQL from _get_data() step by step."""
    try:
        # Test 1: basic select (should work — same as debug2)
        r1 = _db.execute("SELECT * FROM detected_files", fetch=True)

        # Test 2: with ORDER BY
        r2 = _db.execute(
            "SELECT * FROM detected_files ORDER BY file_name", fetch=True
        )

        # Test 3: the exact query from _get_data
        r3 = _db.execute(
            "SELECT * FROM detected_files ORDER BY is_ai_agent DESC, "
            "is_script DESC, is_main_file DESC, file_name", fetch=True
        )

        return jsonify({
            "test1_basic":      len(r1) if r1 else 0,
            "test2_order":      len(r2) if r2 else 0,
            "test3_full_order": len(r3) if r3 else 0,
            "r1_type":          str(type(r1)),
            "r3_type":          str(type(r3)),
            "r3_is_none":       r3 is None,
        })
    except Exception as e:
        import traceback
        return jsonify(
            {"error": str(e), "traceback": traceback.format_exc()}
        ), 500


@application.get("/debug6")
def debug6():
    """Call _get_data() and dump every intermediate value."""
    import traceback
    info = {
        "_db_is_None":      _db is None,
        "_monitor_is_None": _monitor is None,
        "_scanner_is_None": _scanner is None,
    }
    try:
        rows = _db.execute(
            "SELECT * FROM detected_files ORDER BY is_ai_agent DESC, "
            "is_script DESC, is_main_file DESC, file_name", fetch=True
        )
        info["raw_rows_type"] = str(type(rows))
        info["raw_rows_len"]  = len(rows) if rows is not None else "None"
        info["raw_rows_bool"] = bool(rows)

        # This is the exact line _get_data uses
        result = [dict(r) for r in (rows or [])]
        info["result_len"] = len(result)
        info["first_row"]  = result[0] if result else None

        m = _monitor.get_all_metrics()
        info["metrics_keys"]      = list(m.keys())
        info["metrics_system"]    = m.get("system", {})
    except Exception as e:
        info["error"]     = str(e)
        info["traceback"] = traceback.format_exc()
    return jsonify(info), 200

@application.get("/debug7")
def debug7():
    return jsonify({
        "monitoring_flag": getattr(_monitor, "monitoring", None),
        "tok_log_keys":    list(getattr(_monitor, "_tok_log", {}).keys()),
        "req_log_keys":    list(getattr(_monitor, "_req_log", {}).keys()),
        "tok_log_sample":  {
            k: len(v) for k, v in
            list(getattr(_monitor, "_tok_log", {}).items())[:5]
        },
        "metrics_tokens":  dict(_monitor.metrics.get("tokens", {})),
        "metrics_system":  _monitor.metrics.get("system", {}),
    })

    
@application.get("/rescan")
def rescan():
    try:
        target = _CFG["scan_path"] or str(BASE_DIR)
        files = _scanner.scan_project(target)
        return jsonify({
            "pid":     os.getpid(),
            "scanned": len(files),
            "path":    target,
            "ai":      sum(1 for f in files if f.get("is_ai_agent")),
            "sc":      sum(1 for f in files if f.get("is_script")),
            "mn":      sum(1 for f in files if f.get("is_main_file")),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
# DASHBOARD DATA — auto-scans if DB empty, works cross-worker
# ══════════════════════════════════════════════════════════════
def _get_data():
    if _db is None or _monitor is None:
        return [], {"system": {}, "tokens": {}, "requests": {}, "resources": {}}
    rows = _db.execute(
        "SELECT * FROM detected_files ORDER BY is_ai_agent DESC, "
        "is_script DESC, is_main_file DESC, file_name", fetch=True
    )
    if not rows and _scanner:
        target = _CFG["scan_path"] or str(BASE_DIR)
        _scanner.scan_project(target)
        rows = _db.execute(
            "SELECT * FROM detected_files ORDER BY is_ai_agent DESC, "
            "is_script DESC, is_main_file DESC, file_name", fetch=True
        )
    return [dict(r) for r in (rows or [])], _monitor.get_all_metrics()


def _html(body):
    return Response(body, status=200, content_type="text/html; charset=utf-8")


def _err_page(page, extra=""):
    return _html(
        "<html><body style='font-family:sans-serif;padding:40px;"
        "background:#0f172a;color:#e2e8f0'>"
        f"<h1>{page} unavailable</h1>"
        f"<pre style='background:#1e293b;padding:16px;color:#f87171'>"
        f"pid          = {os.getpid()}\n"
        f"_HTMLBuilder = {_HTMLBuilder}\n"
        f"_db          = {_db}\n"
        f"_scanner     = {_scanner}\n"
        f"_monitor     = {_monitor}\n"
        f"import error: {_IMPORT_ERROR}\n"
        f"{extra}"
        "</pre>"
        "<p><a href='/' style='color:#60a5fa'>Home</a></p>"
        "</body></html>"
    )


@application.get("/dashboard")
def dashboard_page():
    if _HTMLBuilder is None:
        return _err_page("Dashboard")
    try:
        f, m = _get_data()
        return _html(_HTMLBuilder.dashboard(f, m))
    except Exception as e:
        return _err_page("Dashboard", f"Runtime: {e}")


@application.get("/files")
def files_page():
    if _HTMLBuilder is None:
        return _err_page("Files")
    try:
        f, _ = _get_data()
        return _html(_HTMLBuilder.files(f))
    except Exception as e:
        return _err_page("Files", f"Runtime: {e}")


@application.get("/agents")
def agents_page():
    if _HTMLBuilder is None:
        return _err_page("Agents")
    try:
        f, m = _get_data()
        return _html(_HTMLBuilder.agents(f, m))
    except Exception as e:
        return _err_page("Agents", f"Runtime: {e}")


@application.get("/monitor")
def monitor_page():
    if _HTMLBuilder is None:
        return _err_page("Monitor")
    try:
        _, m = _get_data()
        return _html(_HTMLBuilder.monitor(m))
    except Exception as e:
        return _err_page("Monitor", f"Runtime: {e}")


@application.get("/model")
def model_page():
    if _HTMLBuilder is None:
        return _err_page("Model")
    try:
        return _html(_HTMLBuilder.model())
    except Exception as e:
        return _err_page("Model", f"Runtime: {e}")


@application.get("/history")
def history_page():
    if _HTMLBuilder is None or _db is None:
        return _err_page("History")
    try:
        return _html(_HTMLBuilder.history(_db))
    except Exception as e:
        return _err_page("History", f"Runtime: {e}")


@application.get("/scan")
def scan_page():
    if _HTMLBuilder is None or _scanner is None:
        return _err_page("Scan")
    try:
        sp = request.args.get(
            "path", _CFG["scan_path"] or str(BASE_DIR)
        )
        scanned = _scanner.scan_project(sp)
        r = {
            "total": len(scanned),
            "ai":    sum(1 for f in scanned if f["is_ai_agent"]),
            "sc":    sum(1 for f in scanned if f["is_script"]),
            "mn":    sum(1 for f in scanned if f["is_main_file"]),
        }
        return _html(_HTMLBuilder.scan_done(r))
    except Exception as e:
        return _err_page("Scan", f"Runtime: {e}")


@application.get("/reset")
def reset_page():
    if _HTMLBuilder is None or _db is None:
        return _err_page("Reset")
    try:
        for t in ("detected_files", "token_usage",
                  "request_usage", "resource_usage"):
            _db.execute(f"DELETE FROM {t}")
        return _html(_HTMLBuilder.reset_done())
    except Exception as e:
        return _err_page("Reset", f"Runtime: {e}")


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


if __name__ == "__main__":
    application.run(
        host="0.0.0.0",
        port=_CFG["port"],
        debug=_CFG["flask_debug"],
    )