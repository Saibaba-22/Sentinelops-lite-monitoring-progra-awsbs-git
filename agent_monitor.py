"""
agent_monitor.py — Core Flask application for SentinelOps-Lite.
This module owns the ``application`` Flask instance that ``app.py`` imports and
extends. It integrates Prometheus metrics and exposes:
  * ``/metrics``            -> Prometheus exposition format (scraped by Prometheus)
  * ``/health``             -> lightweight HTML health probe (used by tests/LB)
  * ``/api/status``         -> aggregated JSON snapshot (used by HTML dashboard)
  * ``/agent/status``       -> latest AI-agent state (JSON)
  * ``/monitor/status``     -> POST receiver used by ``agent.py`` CI release-gate
Business logic from the original application is preserved; monitoring is layered
on top via request hooks and background collectors.
"""
import os
import time
from flask import Flask, Response, jsonify, request, render_template
from werkzeug.exceptions import HTTPException
from monitoring.metrics import (
    app_requests_total,
    app_request_duration_seconds,
    app_errors_total,
    app_exceptions_total,
    http_status_codes_total,
    app_active_sessions,
    app_active_users,
    app_uptime_seconds,
    app_restart_total,
    python_process_resident_memory_bytes,
    python_process_cpu_percent,
    python_thread_count,
    agent_state,
    agent_tasks_total,
    agent_token_usage_total,
    agent_api_calls_total,
    AGENT_STATES,
    APP_STATS,
    generate_latest,
    CONTENT_TYPE_LATEST,
    start_metrics_updater,
    update_metrics,
    agent_state,
    agent_last_decision,
    agent_model_info,
    agent_prompt_tokens_total,
    agent_completion_tokens_total,
    agent_token_usage_total,
    agent_api_calls_total,
    agent_tasks_total,
    agent_api_key_count,
    agent_last_run_timestamp_seconds,
    agent_execution_time_seconds,
    agent_execution_duration_seconds,
    agent_api_response_time_seconds,
    AGENT_STATES,
    AGENT_DECISIONS,
)
from monitoring import collectors
from monitoring import agent_state as agent_state_store
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
application = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
)
application.config["ACTIVE_SESSIONS"] = 0
application.config["ACTIVE_USERS"] = 0
# ---------------------------------------------------------------------------
# Request instrumentation (feeds both Prometheus metrics and APP_STATS)
# ---------------------------------------------------------------------------
@application.before_request
def _start_timer():
    request._start_time = time.time()
@application.after_request
def _record_metrics(response):
    # Never count the metrics endpoint itself.
    if request.path == "/metrics":
        return response
    duration = time.time() - getattr(request, "_start_time", time.time())
    method = request.method
    endpoint = request.path
    status = str(response.status_code)
    app_requests_total.labels(method, endpoint, status).inc()
    app_request_duration_seconds.labels(method, endpoint).observe(duration)
    http_status_codes_total.labels(code=status).inc()
    APP_STATS["total_requests"] += 1
    APP_STATS["total_request_time"] += duration
    if response.status_code >= 500:
        app_errors_total.inc()
        app_exceptions_total.inc()
        APP_STATS["exceptions"] += 1
        APP_STATS["failed_requests"] += 1
    elif response.status_code < 400:
        APP_STATS["success_requests"] += 1
    else:
        APP_STATS["failed_requests"] += 1
    return response
@application.errorhandler(Exception)
def _handle_exception(error):
    app_exceptions_total.inc()
    APP_STATS["exceptions"] += 1
    if isinstance(error, HTTPException):
        return jsonify(error=str(error)), error.code
    return jsonify(error="internal server error"), 500
# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@application.route("/metrics")
def metrics():
    # Use content_type directly so Flask does not re-append the charset.
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)
@application.route("/health")
def health():
    # Returns HTML so the existing test (and simple LB health checks) pass.
    return Response("<html><body>healthy</body></html>", mimetype="text/html")
@application.route("/api/status")
def api_status():
    return jsonify(collectors.build_status())
@application.route("/agent/status")
def agent_status():
    """
    Return backward-compatible top-level agent status plus all three agents.
    Top-level fields keep existing tests/dashboard clients working.
    The `agents` field contains detailed per-agent monitoring state.
    """
    state_data = agent_state_store.load()
    agents = state_data.get("agents", {})
    # Select the agent with the newest last_run value as the summary agent.
    latest_agent = {}
    for agent_data in agents.values():
        if not latest_agent:
            latest_agent = agent_data
            continue
        if str(agent_data.get("last_run") or "") > str(
            latest_agent.get("last_run") or ""
        ):
            latest_agent = agent_data
    # Fallback values preserve old /agent/status response behavior.
    response = {
        "status": str(
    latest_agent.get("status", state_data.get("status", "Idle"))
).capitalize(),
        "decision": latest_agent.get(
            "decision",
            state_data.get("decision", "none"),
        ),
        "provider": latest_agent.get(
            "provider",
            state_data.get("provider", "gemini"),
        ),
        "model": latest_agent.get(
            "model",
            state_data.get("model", "gemini-2.5-flash"),
        ),
        "prompt_tokens": latest_agent.get(
            "prompt_tokens",
            state_data.get("prompt_tokens", 0),
        ),
        "completion_tokens": latest_agent.get(
            "completion_tokens",
            state_data.get("completion_tokens", 0),
        ),
        "total_tokens": latest_agent.get(
            "total_tokens",
            state_data.get("total_tokens", 0),
        ),
        "tokens": latest_agent.get(
            "total_tokens",
            state_data.get("tokens", 0),
        ),
        "requests": latest_agent.get(
            "requests",
            state_data.get("requests", 0),
        ),
        "api_key_count": latest_agent.get(
            "api_key_count",
            state_data.get("api_key_count", 0),
        ),
        "api_keys": latest_agent.get(
            "api_key_count",
            state_data.get("api_keys", 0),
        ),
        "last_run": latest_agent.get(
            "last_run",
            state_data.get("last_run"),
        ),
        "execution_time_seconds": latest_agent.get(
            "execution_time_seconds",
            state_data.get("execution_time_seconds", 0),
        ),
        # New detailed data for all three CI agents.
        "agents": agents,
    }
    return jsonify(response)
@application.route("/monitor/status", methods=["POST"])
def monitor_status():
    """
    Receives monitoring events from CI AI agents.
    Required:
      agent_name, stage, status
    Optional:
      cloud, provider, model,
      prompt_tokens, completion_tokens, total_tokens,
      requests, api_key_count,
      execution_time_seconds, api_response_time_seconds,
      decision, error
    """
    # Recommended: protect this endpoint with a secret.
    expected_token = os.getenv("MONITOR_TOKEN")
    if expected_token and request.headers.get("X-Monitor-Token") != expected_token:
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name", "unknown")).strip().lower()
    stage = str(data.get("stage", "unknown")).strip().lower()
    cloud = str(data.get("cloud", "unknown")).strip().lower()
    provider = str(data.get("provider", "gemini")).strip().lower()
    model = str(data.get("model", "unknown")).strip()
    # status: idle / running / approved / rejected / failed / healthy
    status = str(data.get("status", "idle")).strip().lower()
    if status not in AGENT_STATES:
        status = "failed"
    # Decision is intentionally separate from state.
    decision = str(data.get("decision", status)).strip().lower()
    if decision not in AGENT_DECISIONS:
        decision = "none"
    prompt_tokens = max(0, int(data.get("prompt_tokens", 0) or 0))
    completion_tokens = max(0, int(data.get("completion_tokens", 0) or 0))
    total_tokens = max(
        0,
        int(data.get("total_tokens", prompt_tokens + completion_tokens) or 0),
    )
    api_requests = max(0, int(data.get("requests", 0) or 0))
    api_key_count = max(0, int(data.get("api_key_count", 1) or 0))
    execution_time = max(0.0, float(data.get("execution_time_seconds", 0) or 0))
    api_response_time = max(
        0.0,
        float(data.get("api_response_time_seconds", 0) or 0),
    )
    labels = {
        "agent_name": agent_name,
        "stage": stage,
        "cloud": cloud,
    }
    # Set exactly one state and one last decision for this agent.
    for item in AGENT_STATES:
        agent_state.labels(**labels, state=item).set(1 if item == status else 0)
    for item in AGENT_DECISIONS:
        agent_last_decision.labels(**labels, decision=item).set(
            1 if item == decision else 0
        )
    # Provider/model metadata. Do not send secrets as labels.
    agent_model_info.labels(**labels).info({
        "provider": provider,
        "model": model,
    })
    agent_api_key_count.labels(**labels, provider=provider).set(api_key_count)
    agent_last_run_timestamp_seconds.labels(**labels).set(time.time())
    # Only increment counters for actual completed AI calls.
    if api_requests:
        api_status = "success" if status not in ("failed",) else "failed"
        agent_api_calls_total.labels(
            **labels,
            provider=provider,
            model=model,
            status=api_status,
        ).inc(api_requests)
    if prompt_tokens:
        agent_prompt_tokens_total.labels(
            **labels, provider=provider, model=model
        ).inc(prompt_tokens)
    if completion_tokens:
        agent_completion_tokens_total.labels(
            **labels, provider=provider, model=model
        ).inc(completion_tokens)
    if total_tokens:
        agent_token_usage_total.labels(
            **labels, provider=provider, model=model
        ).inc(total_tokens)
    # Do not increment execution/task counters for a "running" status update.
    if status not in ("idle", "running"):
        result = (
            "Approved" if status in ("Approved", "healthy")
            else "rejected" if status == "rejected"
            else "failed"
        )
        agent_tasks_total.labels(**labels, result=result).inc()
        agent_execution_time_seconds.labels(**labels).set(execution_time)
        agent_execution_duration_seconds.labels(**labels).observe(execution_time)
        if api_response_time:
            agent_api_response_time_seconds.labels(
                **labels,
                provider=provider,
                model=model,
            ).observe(api_response_time)
    # Persist latest state for dashboard/API.
    stored = agent_state_store.load()
    stored.setdefault("agents", {})
    stored["agents"][agent_name] = {
        "agent_name": agent_name,
        "stage": stage,
        "cloud": cloud,
        "status": status,
        "decision": decision,
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "requests": api_requests,
        "api_key_count": api_key_count,
        "execution_time_seconds": execution_time,
        "api_response_time_seconds": api_response_time,
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    agent_state_store.save(stored)
    return jsonify(ok=True, agent=agent_name, status=status)
@application.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")
# ---------------------------------------------------------------------------
# Active session / user helpers (example hooks for real auth later)
# ---------------------------------------------------------------------------
def set_active_counts(sessions: int, users: int):
    application.config["ACTIVE_SESSIONS"] = sessions
    application.config["ACTIVE_USERS"] = users
    app_active_sessions.set(sessions)
    app_active_users.set(users)
# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
update_metrics()
start_metrics_updater(interval=int(os.getenv("METRICS_INTERVAL", "5")))
