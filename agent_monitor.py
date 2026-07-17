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
    agent_total_decisions,
    agent_current_task,
    agent_last_task,
    AGENT_STATES,
    APP_STATS,
    generate_latest,
    CONTENT_TYPE_LATEST,
    start_metrics_updater,
    update_metrics,
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
    return jsonify(agent_state_store.load())


@application.route("/monitor/status", methods=["POST"])
def monitor_status():
    """Receiver for the ``agent.py`` CI release-gate.

    Expected JSON payload (see agent.py):
        {status, tokens, requests, api_keys, model, last_run, api_key_name}
    """
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "Unknown"))
    tokens = int(data.get("tokens", 0) or 0)
    reqs = int(data.get("requests", 1) or 1)

    # Update the agent state gauge (exactly one state active).
    active = status.lower()
    for name in AGENT_STATES:
        agent_state.labels(state=name).set(1 if name == active else 0)

    if active == "approved":
        agent_tasks_total.labels(result="approved").inc()
    elif active == "rejected":
        agent_tasks_total.labels(result="rejected").inc()
    elif active == "failed":
        agent_tasks_total.labels(result="failed").inc()

    # Approved / Healthy -> successful API call, otherwise a failed call.
    call_status = "success" if active in ("approved", "healthy") else "failed"
    agent_api_calls_total.labels(status=call_status).inc(reqs)
    agent_token_usage_total.inc(tokens)
    agent_total_decisions.inc()

    # Persist the broadcast so dashboards can render it without Prometheus.
    stored = agent_state_store.load()
    for key in ("status", "tokens", "requests", "api_keys", "model", "last_run", "api_key_name"):
        if key in data:
            stored[key] = data[key]
    agent_state_store.save(stored)

    return jsonify(ok=True)


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
