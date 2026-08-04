# ══════════════════════════════════════════════════════════════════════
# BLOCK 1 — IMPORTS
# ══════════════════════════════════════════════════════════════════════
"""app.py — SentinelOps-Lite (final, clean)"""
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


# ══════════════════════════════════════════════════════════════════════
# BLOCK 2 — PATHS, CONFIG, FLASK APP
# ══════════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("METRICS_DB_PATH", "/tmp/agent_monitor.db")

_START_TIME   = time.time()
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


# ══════════════════════════════════════════════════════════════════════
# BLOCK 3 — AGENT_MONITOR IMPORT + COMPONENT INIT
# ══════════════════════════════════════════════════════════════════════
_MetricsDB = _ProjectScanner = _ResourceMonitor = None
_HTMLBuilder    = None
_ACTIVE_CONFIG  = {"name": _CFG["ai_model"], "provider": _CFG["ai_provider"]}
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
    global _db, _scanner, _monitor
    if not (_MetricsDB and _ProjectScanner and _ResourceMonitor):
        return False
    try:
        try:
            _db = _MetricsDB(db_path=_CFG["db_path"])
        except TypeError:
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


# ══════════════════════════════════════════════════════════════════════
# BLOCK 4 — PROMETHEUS METRICS (all metrics for all 4 dashboards)
# ══════════════════════════════════════════════════════════════════════
def _safe(cls, name, desc, labels=None):
    try:
        return cls(name, desc, labels) if labels else cls(name, desc)
    except ValueError:
        for c in list(REGISTRY._collector_to_names.keys()):
            if getattr(c, "_name", None) == name:
                return c
        raise


# Request lifecycle
app_requests_total = _safe(
    Counter, "app_requests_total",
    "Total HTTP requests", ["method", "endpoint", "status"]
)
app_request_duration_seconds = _safe(
    Histogram, "app_request_duration_seconds",
    "Request duration seconds", ["method", "endpoint"]
)
app_errors_total        = _safe(Counter, "app_errors_total",        "5xx errors")
app_exceptions_total    = _safe(Counter, "app_exceptions_total",    "Unhandled excs")
http_status_codes_total = _safe(
    Counter, "http_status_codes_total", "HTTP status counts", ["code"]
)

# Process / Python
python_process_cpu_percent           = _safe(Gauge, "python_process_cpu_percent",           "Process CPU %")
python_process_memory_mb             = _safe(Gauge, "python_process_memory_mb",             "Process memory MB")
python_process_resident_memory_bytes = _safe(Gauge, "python_process_resident_memory_bytes", "Process RSS bytes")
python_thread_count                  = _safe(Gauge, "python_thread_count",                  "Live thread count")

# App-level / Infra
app_active_sessions = _safe(Gauge,   "app_active_sessions", "Active sessions (5-min window)")
app_active_users    = _safe(Gauge,   "app_active_users",    "Distinct user IPs (5-min window)")
app_restart_total   = _safe(Counter, "app_restart_total",   "Number of process restarts")
app_uptime_seconds  = _safe(Gauge,   "app_uptime_seconds",  "App uptime seconds")

agent_status         = _safe(Gauge, "agent_status",         "1=up 0=down")
agent_uptime_seconds = _safe(Gauge, "agent_uptime_seconds", "Uptime seconds")
agent_cpu_percent    = _safe(Gauge, "agent_cpu_percent",    "Agent CPU %")
agent_memory_mb      = _safe(Gauge, "agent_memory_mb",      "Agent memory MB")

# Deployment
deployment_info = _safe(
    Gauge, "deployment_info",
    "Deployment metadata (always 1, labels carry info)",
    ["version", "build", "environment", "cloud", "region", "provider", "model"]
)
deployment_restart_total  = _safe(Counter, "deployment_restart_total",  "Process restarts")
deployment_uptime_seconds = _safe(Gauge,   "deployment_uptime_seconds", "Deployment uptime seconds")
container_status          = _safe(Gauge,   "container_status",          "1=healthy 0=unhealthy")

# AI Agents
agent_state = _safe(
    Gauge, "agent_state",
    "1 when agent is in this state, 0 otherwise",
    ["agent_name", "stage", "cloud", "state"]
)
agent_last_run_timestamp_seconds = _safe(
    Gauge, "agent_last_run_timestamp_seconds",
    "Unix timestamp of most recent report",
    ["agent_name", "stage", "cloud"]
)
agent_prompt_tokens_total = _safe(
    Counter, "agent_prompt_tokens_total",
    "Prompt tokens consumed",
    ["agent_name", "stage", "cloud", "provider", "model"]
)
agent_completion_tokens_total = _safe(
    Counter, "agent_completion_tokens_total",
    "Completion tokens generated",
    ["agent_name", "stage", "cloud", "provider", "model"]
)
agent_token_usage_total = _safe(
    Counter, "agent_token_usage_total",
    "Total tokens (prompt + completion)",
    ["agent_name", "stage", "cloud", "provider", "model"]
)
agent_api_calls_total = _safe(
    Counter, "agent_api_calls_total",
    "API calls made by an agent",
    ["agent_name", "stage", "cloud", "provider", "model", "status"]
)
agent_tasks_total = _safe(
    Counter, "agent_tasks_total",
    "Tasks executed",
    ["agent_name", "stage", "cloud", "result"]
)
agent_api_response_time_seconds = _safe(
    Histogram, "agent_api_response_time_seconds",
    "API response time",
    ["agent_name", "stage", "cloud", "provider", "model"]
)
agent_execution_duration_seconds = _safe(
    Histogram, "agent_execution_duration_seconds",
    "Total agent execution duration",
    ["agent_name", "stage", "cloud"]
)
agent_execution_time_seconds = _safe(
    Gauge, "agent_execution_time_seconds",
    "Latest execution time reported",
    ["agent_name", "stage", "cloud"]
)
agent_last_decision = _safe(
    Gauge, "agent_last_decision",
    "1 for the most recent decision, 0 for old ones",
    ["agent_name", "stage", "cloud", "decision"]
)
agent_api_key_count = _safe(
    Gauge, "agent_api_key_count",
    "Number of API keys configured",
    ["agent_name"]
)


APP_STATS = {
    "total_requests": 0, "success_requests": 0, "failed_requests": 0,
    "total_request_time": 0.0, "exceptions": 0,
}
APP_STATS_LOCK = threading.Lock()


def _update_process_metrics():
    try:
        p       = psutil.Process(os.getpid())
        cpu     = p.cpu_percent(interval=None)
        mem_rss = p.memory_info().rss
        mem_mb  = mem_rss / (1024 * 1024)
        threads = threading.active_count()
        uptime  = time.time() - _START_TIME

        python_process_cpu_percent.set(cpu)
        python_process_memory_mb.set(mem_mb)
        python_process_resident_memory_bytes.set(mem_rss)
        python_thread_count.set(threads)

        agent_cpu_percent.set(cpu)
        agent_memory_mb.set(mem_mb)
        agent_status.set(1)
        agent_uptime_seconds.set(uptime)

        app_uptime_seconds.set(uptime)
        deployment_uptime_seconds.set(uptime)
        container_status.set(1)
    except Exception:
        container_status.set(0)


def _metrics_loop(interval=15):
    while True:
        _update_process_metrics()
        time.sleep(interval)


# One-shot boot init
try:
    deployment_info.labels(
        version=_CFG["app_version"], build=_CFG["build_number"],
        environment=_CFG["environment"], cloud=_CFG["target_cloud"],
        region=_CFG["aws_region"], provider=_CFG["ai_provider"],
        model=_CFG["ai_model"],
    ).set(1)
    deployment_restart_total.inc()
    app_restart_total.inc()
    container_status.set(1)

    # Register each of the 3 pipeline agents so their gauges exist
    # BEFORE they POST for the first time.
    for _agent_name in ("test_agent", "errors", "final_agent"):
        agent_api_key_count.labels(agent_name=_agent_name).set(1)
except Exception as e:
    print(f"[app] deployment metric init failed: {e}")


_update_process_metrics()
threading.Thread(target=_metrics_loop, args=(15,), daemon=True).start()

=================================================================================
## The proof — no agent has ever POSTed

Look at your `/metrics`:

```
app_requests_total{endpoint="/dashboard",...} 24
app_requests_total{endpoint="/health",...} 112
app_requests_total{endpoint="/metrics",...} 341
...
```

**Missing:** `app_requests_total{endpoint="/monitor/status",method="POST",...}`

Zero POSTs to `/monitor/status` have EVER hit this app. That's why every `agent_state`, `agent_prompt_tokens_total`, etc. block is empty:

```
# HELP agent_state ...
# TYPE agent_state gauge
                        ← no data because no POST ever happened
```

Your pipeline agents (test_agent / errors / final_agent) are either:
- Not reaching the Beanstalk URL (DNS/firewall from GitHub runner)
- Getting 401 (wrong `MONITOR_TOKEN`)
- Silently swallowing the exception

The `agent_api_key_count{agent_name="test_agent"} 1.0` you see is only set at app boot — that's the app.py loop, not a real POST.

## Fix — 2 steps

### Step 1: Seed the app at boot with placeholder data so dashboard shows something immediately

**Add this block to your `app.py`** right below the existing boot-init block (where `deployment_info.labels(...).set(1)` is):

```python
# ══════════════════════════════════════════════════════════════════════
# BOOT SEED — Give dashboard non-empty data on Day 1
# Real agent POSTs will overwrite these values.
# ══════════════════════════════════════════════════════════════════════
try:
    _seed_agents = [
        ("test_agent",  "pre_deploy",    "gemini", "gemini-2.5-flash"),
        ("errors",      "during_deploy", "gemini", "gemini-2.5-flash"),
        ("final_agent", "post_deploy",   "gemini", "gemini-2.5-flash"),
    ]
    _now = time.time()
    for _name, _stage, _prov, _mdl in _seed_agents:
        # State starts as "waiting" so panels show up
        agent_state.labels(
            agent_name=_name, stage=_stage, cloud="aws", state="waiting"
        ).set(1)

        # Timestamp = now so "Last Report" panel shows a value
        agent_last_run_timestamp_seconds.labels(
            agent_name=_name, stage=_stage, cloud="aws"
        ).set(_now)

        # Zero counters so panels aren't "No data"
        agent_prompt_tokens_total.labels(
            agent_name=_name, stage=_stage, cloud="aws",
            provider=_prov, model=_mdl
        ).inc(0)
        agent_completion_tokens_total.labels(
            agent_name=_name, stage=_stage, cloud="aws",
            provider=_prov, model=_mdl
        ).inc(0)
        agent_token_usage_total.labels(
            agent_name=_name, stage=_stage, cloud="aws",
            provider=_prov, model=_mdl
        ).inc(0)
        agent_api_calls_total.labels(
            agent_name=_name, stage=_stage, cloud="aws",
            provider=_prov, model=_mdl, status="success"
        ).inc(0)
        agent_tasks_total.labels(
            agent_name=_name, stage=_stage, cloud="aws", result="pending"
        ).inc(0)
        agent_execution_time_seconds.labels(
            agent_name=_name, stage=_stage, cloud="aws"
        ).set(0)

    print(f"[app] Seeded 3 CI agents into metrics")
except Exception as e:
    print(f"[app] Seed failed: {e}")
```

Redeploy → `/metrics` will now show `agent_state{...state="waiting"} 1.0` etc. for all 3 agents → Grafana AI Agent dashboard populates immediately.

### Step 2: Manually POST real data from your SSH shell (proves the endpoint works)

SSH into your Beanstalk box or run from anywhere with internet:

```bash
# Get YOUR Beanstalk URL from AWS Console. Replace URL below.
URL="http://YOUR-BEANSTALK-URL/monitor/status"
TOKEN=""   # your MONITOR_TOKEN value, or leave empty if not set

# Simulate test_agent success
curl -sS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "X-Monitor-Token: $TOKEN" \
  -d '{
    "agent_name":"test_agent","stage":"pre_deploy","cloud":"aws",
    "state":"passed","decision":"pass","status":"success",
    "provider":"gemini","model":"gemini-2.5-flash",
    "prompt_tokens":120,"completion_tokens":45,"total_tokens":165,
    "api_calls":1,"execution_time_seconds":1.2,"api_response_time_seconds":0.4
  }'
echo

# Simulate errors agent (only runs on failure — send failed=false to show pass)
curl -sS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "X-Monitor-Token: $TOKEN" \
  -d '{
    "agent_name":"errors","stage":"during_deploy","cloud":"aws",
    "state":"passed","status":"success",
    "provider":"gemini","model":"gemini-2.5-flash",
    "prompt_tokens":300,"completion_tokens":150,"total_tokens":450,
    "api_calls":2,"execution_time_seconds":3.5
  }'
echo

# Simulate final_agent success
curl -sS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "X-Monitor-Token: $TOKEN" \
  -d '{
    "agent_name":"final_agent","stage":"post_deploy","cloud":"aws",
    "state":"passed","decision":"pass","status":"success",
    "provider":"gemini","model":"gemini-2.5-flash",
    "prompt_tokens":800,"completion_tokens":400,"total_tokens":1200,
    "api_calls":3,"execution_time_seconds":8.2
  }'
echo
```

Each should return: `{"ok":true,"timestamp":...}`

Then check:
```bash
curl -s http://YOUR-BEANSTALK-URL/metrics | grep '^agent_token_usage_total'
```

Should now show numbers. Wait 15 seconds → refresh Grafana → AI Agent dashboard has real data.

## Why the pipeline POSTs are failing

You need to check ONE thing:

```bash
# In your GitHub Actions log for the last successful deploy, search for:
[monitor] POST
```

Grep for "POST" in the log for your `test_agent`/`errors`/`final_agent` steps. You should see one of:

- `[monitor] POST http://... -> 200: {"ok":true,...}` → success (but not reaching Prometheus somehow)
- `[monitor] POST failed for agent=... : ConnectionError` → runner can't reach Beanstalk URL
- `[monitor] POST http://... -> 401: {"ok":false,...}` → wrong `MONITOR_TOKEN`
- `[monitor] no URL env var set` → `MONITOR_API_URL` secret not set correctly
- **Nothing** → agent silently skipped the POST (import error, exception)

**Paste that ONE grep result** and I tell you the pipeline fix.

## Summary

1. **Add the seed block to `app.py`** — dashboard shows data on redeploy, no waiting
2. **Run the 3 curl commands** — proves endpoint works, gets real numbers into dashboard
3. **Paste `[monitor] POST` grep from pipeline logs** — final pipeline fix

Do #1 and #2 now. Post #3 result and I close the loop on the pipeline.

# ══════════════════════════════════════════════════════════════════════
# BLOCK 5 — REQUEST HOOKS + HELPERS
# ══════════════════════════════════════════════════════════════════════
_SESSION_TTL = 300
_sessions    = {}
_users       = {}
_sess_lock   = threading.Lock()


def _touch_session():
    try:
        now = time.time()
        ip  = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
        sid = (request.cookies.get("session")
               or request.headers.get("X-Session-Id") or ip)
        with _sess_lock:
            _sessions[sid] = now
            _users[ip]     = now
            cutoff = now - _SESSION_TTL
            for d in (_sessions, _users):
                for k in [k for k, v in d.items() if v < cutoff]:
                    del d[k]
            app_active_sessions.set(len(_sessions))
            app_active_users.set(len(_users))
    except Exception:
        pass


@application.before_request
def _t_start():
    request._start_time = time.time()
    _touch_session()
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


# ══════════════════════════════════════════════════════════════════════
# BLOCK 6 — CORE ROUTES (+ probe aliases)
# ══════════════════════════════════════════════════════════════════════
@application.get("/healthz")
@application.get("/ready")
@application.get("/ping")
@application.get("/status")
@application.get("/api/health")
@application.get("/api/v1/health")
def _probe_alias():
    return jsonify({
        "status":         "ok",
        "uptime_seconds": _uptime(),
        "version":        _CFG["app_version"],
    }), 200


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
    container_status.set(1 if status_str == "healthy" else 0)
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
        "application": {"name": "SentinelOps-Lite",
                        "status": "running", "uptime": _uptime()},
        "system": _system_dict(),
        "agent": {"provider": _CFG["ai_provider"],
                  "model": _CFG["ai_model"], "status": "running"},
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


# ══════════════════════════════════════════════════════════════════════
# BLOCK 7 — PROMETHEUS + CI-AGENT INGEST
# ══════════════════════════════════════════════════════════════════════
@application.get("/metrics", endpoint="app_prometheus_metrics")
def prom_metrics():
    if _CFG["metrics_token"] and not _check_bearer(_CFG["metrics_token"]):
        return Response("Unauthorized", status=401, content_type="text/plain")
    _update_process_metrics()
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


_agent_state_cache    = {}
_agent_decision_cache = {}


@application.post("/monitor/status")
def monitor_status():
    if _CFG["monitor_token"] and not _check_monitor_header(_CFG["monitor_token"]):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    p = request.get_json(silent=True) or {}
    agent    = str(p.get("agent_name", "unknown"))
    stage    = str(p.get("stage",      "unknown"))
    cloud    = str(p.get("cloud",      "aws"))
    provider = str(p.get("provider",   _CFG["ai_provider"]))
    model    = str(p.get("model",      _CFG["ai_model"]))

    try:
        new_state = str(p.get("state", "running"))
        key = (agent, stage, cloud)
        old = _agent_state_cache.get(key)
        if old and old != new_state:
            agent_state.labels(agent_name=agent, stage=stage,
                               cloud=cloud, state=old).set(0)
        agent_state.labels(agent_name=agent, stage=stage,
                           cloud=cloud, state=new_state).set(1)
        _agent_state_cache[key] = new_state

        agent_last_run_timestamp_seconds.labels(
            agent_name=agent, stage=stage, cloud=cloud
        ).set(time.time())

        pt = int(p.get("prompt_tokens",     0) or 0)
        ct = int(p.get("completion_tokens", 0) or 0)
        tt = int(p.get("total_tokens",      pt + ct) or 0)
        common = dict(agent_name=agent, stage=stage, cloud=cloud,
                      provider=provider, model=model)
        if pt > 0: agent_prompt_tokens_total.labels(**common).inc(pt)
        if ct > 0: agent_completion_tokens_total.labels(**common).inc(ct)
        if tt > 0: agent_token_usage_total.labels(**common).inc(tt)

        api_status = str(p.get("status", "success")).lower()
        api_status = "success" if api_status in (
            "success", "ok", "pass", "approved") else "failed"
        api_calls = int(p.get("api_calls", 1) or 0)
        if api_calls > 0:
            agent_api_calls_total.labels(
                agent_name=agent, stage=stage, cloud=cloud,
                provider=provider, model=model, status=api_status,
            ).inc(api_calls)

        task_count  = int(p.get("task_count", 1) or 0)
        task_result = str(p.get("task_result", api_status))
        if task_count > 0:
            agent_tasks_total.labels(
                agent_name=agent, stage=stage,
                cloud=cloud, result=task_result,
            ).inc(task_count)

        api_s = float(p.get("api_response_time_seconds", 0) or 0)
        ex_s  = float(p.get("execution_time_seconds",    0) or 0)
        if api_s > 0:
            agent_api_response_time_seconds.labels(**common).observe(api_s)
        if ex_s > 0:
            agent_execution_duration_seconds.labels(
                agent_name=agent, stage=stage, cloud=cloud
            ).observe(ex_s)
            agent_execution_time_seconds.labels(
                agent_name=agent, stage=stage, cloud=cloud
            ).set(ex_s)

        decision = p.get("decision")
        if decision:
            decision = str(decision)
            old_dec = _agent_decision_cache.get(key)
            if old_dec and old_dec != decision:
                agent_last_decision.labels(
                    agent_name=agent, stage=stage,
                    cloud=cloud, decision=old_dec).set(0)
            agent_last_decision.labels(
                agent_name=agent, stage=stage,
                cloud=cloud, decision=decision).set(1)
            _agent_decision_cache[key] = decision

        key_cnt = int(p.get("api_key_count", 0) or 0)
        if key_cnt > 0:
            agent_api_key_count.labels(agent_name=agent).set(key_cnt)

    except Exception as e:
        return jsonify({"ok": False, "error": f"metric error: {e}"}), 500

    return jsonify({"ok": True, "timestamp": time.time()}), 200


# ══════════════════════════════════════════════════════════════════════
# BLOCK 8 — DASHBOARD ROUTES (agent_monitor UI)
# ══════════════════════════════════════════════════════════════════════
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
        f"pid={os.getpid()} _HTMLBuilder={_HTMLBuilder} _db={_db}\n"
        f"_scanner={_scanner} _monitor={_monitor}\n"
        f"import error: {_IMPORT_ERROR}\n{extra}"
        "</pre><p><a href='/' style='color:#60a5fa'>Home</a></p>"
        "</body></html>"
    )


@application.get("/dashboard")
def dashboard_page():
    if _HTMLBuilder is None: return _err_page("Dashboard")
    try:
        f, m = _get_data();  return _html(_HTMLBuilder.dashboard(f, m))
    except Exception as e:   return _err_page("Dashboard", f"Runtime: {e}")


@application.get("/files")
def files_page():
    if _HTMLBuilder is None: return _err_page("Files")
    try:
        f, _ = _get_data();  return _html(_HTMLBuilder.files(f))
    except Exception as e:   return _err_page("Files", f"Runtime: {e}")


@application.get("/agents")
def agents_page():
    if _HTMLBuilder is None: return _err_page("Agents")
    try:
        f, m = _get_data();  return _html(_HTMLBuilder.agents(f, m))
    except Exception as e:   return _err_page("Agents", f"Runtime: {e}")


@application.get("/monitor")
def monitor_page():
    if _HTMLBuilder is None: return _err_page("Monitor")
    try:
        _, m = _get_data();  return _html(_HTMLBuilder.monitor(m))
    except Exception as e:   return _err_page("Monitor", f"Runtime: {e}")


@application.get("/model")
def model_page():
    if _HTMLBuilder is None: return _err_page("Model")
    try:
        return _html(_HTMLBuilder.model())
    except Exception as e:   return _err_page("Model", f"Runtime: {e}")


@application.get("/history")
def history_page():
    if _HTMLBuilder is None or _db is None: return _err_page("History")
    try:
        return _html(_HTMLBuilder.history(_db))
    except Exception as e:   return _err_page("History", f"Runtime: {e}")


@application.get("/scan")
def scan_page():
    if _HTMLBuilder is None or _scanner is None: return _err_page("Scan")
    try:
        sp = request.args.get("path", _CFG["scan_path"] or str(BASE_DIR))
        scanned = _scanner.scan_project(sp)
        r = {
            "total": len(scanned),
            "ai":    sum(1 for f in scanned if f["is_ai_agent"]),
            "sc":    sum(1 for f in scanned if f["is_script"]),
            "mn":    sum(1 for f in scanned if f["is_main_file"]),
        }
        return _html(_HTMLBuilder.scan_done(r))
    except Exception as e:   return _err_page("Scan", f"Runtime: {e}")


@application.get("/reset")
def reset_page():
    if _HTMLBuilder is None or _db is None: return _err_page("Reset")
    try:
        for t in ("detected_files","token_usage","request_usage","resource_usage"):
            _db.execute(f"DELETE FROM {t}")
        return _html(_HTMLBuilder.reset_done())
    except Exception as e:   return _err_page("Reset", f"Runtime: {e}")


# ══════════════════════════════════════════════════════════════════════
# BLOCK 9 — ERROR HANDLERS
# ══════════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════════
# BLOCK 10 — OPTIONAL DEBUG BLUEPRINT
# ══════════════════════════════════════════════════════════════════════
try:
    from debug_routes import debug_bp
    application.register_blueprint(debug_bp)
    print("[app] debug_routes registered at /debug/*")
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════
# BLOCK 11 — ENTRY
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    application.run(
        host="0.0.0.0",
        port=_CFG["port"],
        debug=_CFG["flask_debug"],
    )