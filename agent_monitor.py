""" 
agent_monitor.py — Core Flask application for SentinelOps-Lite.

This module owns the ``application`` Flask instance that ``app.py`` imports
and extends.  It integrates Prometheus metrics and exposes:

  * ``/metrics``            -> Prometheus exposition format (scraped by Prometheus)
  * ``/health``             -> lightweight HTML health probe (used by tests/LB)
  * ``/api/status``         -> aggregated JSON snapshot (used by HTML dashboard)
  * ``/agent/status``       -> latest AI-agent state (JSON)
  * ``/monitor/status``     -> GET: public HTML dashboard | POST: CI agent receiver
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
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@application.route("/health")
def health():
    return Response("<html><body>healthy</body></html>", mimetype="text/html")


@application.route("/api/status")
def api_status():
    return jsonify(collectors.build_status())


@application.route("/agent/status")
def agent_status():
    """
    Return backward-compatible top-level agent status plus all three agents.
    """
    state_data = agent_state_store.load()
    agents = state_data.get("agents", {})

    latest_agent = {}
    for agent_data in agents.values():
        if not latest_agent:
            latest_agent = agent_data
            continue
        if str(agent_data.get("last_run") or "") > str(
            latest_agent.get("last_run") or ""
        ):
            latest_agent = agent_data

    response = {
        "status": str(
            latest_agent.get("status", state_data.get("status", "Idle"))
        ).capitalize(),
        "decision": latest_agent.get(
            "decision", state_data.get("decision", "none")
        ),
        "provider": latest_agent.get(
            "provider", state_data.get("provider", "gemini")
        ),
        "model": latest_agent.get(
            "model", state_data.get("model", "gemini-2.5-flash")
        ),
        "prompt_tokens": latest_agent.get(
            "prompt_tokens", state_data.get("prompt_tokens", 0)
        ),
        "completion_tokens": latest_agent.get(
            "completion_tokens", state_data.get("completion_tokens", 0)
        ),
        "total_tokens": latest_agent.get(
            "total_tokens", state_data.get("total_tokens", 0)
        ),
        "tokens": latest_agent.get(
            "total_tokens", state_data.get("tokens", 0)
        ),
        "requests": latest_agent.get(
            "requests", state_data.get("requests", 0)
        ),
        "api_key_count": latest_agent.get(
            "api_key_count", state_data.get("api_key_count", 0)
        ),
        "api_keys": latest_agent.get(
            "api_key_count", state_data.get("api_keys", 0)
        ),
        "last_run": latest_agent.get(
            "last_run", state_data.get("last_run")
        ),
        "execution_time_seconds": latest_agent.get(
            "execution_time_seconds", state_data.get("execution_time_seconds", 0)
        ),
        "agents": agents,
    }
    return jsonify(response)


# ──────────────────────────────────────────────────────────────────────────
# /monitor/status — GET: public browser dashboard | POST: CI agent receiver
# ──────────────────────────────────────────────────────────────────────────

@application.route("/monitor/status", methods=["GET"])
def monitor_status_get():
    """
    Public endpoint — browse this in a web browser to see real monitoring data.
    No authentication required. Shows:
      - Application stats (requests, errors, uptime)
      - Agent states (all 3 CI agents)
      - Prometheus scrape stats
    Returns HTML that refreshes every 10 seconds.
    """
    state_data = agent_state_store.load()
    agents = state_data.get("agents", {})
    app_status = collectors.build_status()

    # Build agent rows HTML
    agent_rows = ""
    if agents:
        for name, data in agents.items():
            status_color = "#22c55e" if data.get("status") in ("approved", "healthy", "idle") else "#ef4444" if data.get("status") == "failed" else "#f59e0b"
            agent_rows += f"""
            <tr>
                <td><strong>{name}</strong></td>
                <td><span style="color:{status_color};font-weight:bold">{data.get('status', 'unknown').capitalize()}</span></td>
                <td>{data.get('decision', 'none').capitalize()}</td>
                <td>{data.get('stage', 'unknown')}</td>
                <td>{data.get('cloud', 'unknown')}</td>
                <td>{data.get('provider', 'unknown')} / {data.get('model', 'unknown')}</td>
                <td>{data.get('total_tokens', 0)}</td>
                <td>{data.get('requests', 0)}</td>
                <td>{data.get('execution_time_seconds', 0)}s</td>
                <td>{data.get('last_run', 'never')}</td>
            </tr>"""
    else:
        agent_rows = '<tr><td colspan="10" style="text-align:center;color:#999">No agent data yet — deploy pipeline to populate</td></tr>'

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>SentinelOps-Lite Monitor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f172a; color: #e2e8f0; padding: 20px; }}
        h1 {{ color: #38bdf8; margin-bottom: 8px; }}
        h2 {{ color: #94a3b8; margin: 20px 0 10px; font-size: 18px; }}
        .subtitle {{ color: #94a3b8; margin-bottom: 20px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                      gap: 12px; margin-bottom: 20px; }}
        .stat-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px;
                    padding: 16px; }}
        .stat-label {{ color: #94a3b8; font-size: 12px; margin-bottom: 4px; }}
        .stat-value {{ color: #f1f5f9; font-size: 24px; font-weight: bold; }}
        .stat-value.good {{ color: #22c55e; }}
        .stat-value.bad {{ color: #ef4444; }}
        .stat-value.warn {{ color: #f59e0b; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b;
               border: 1px solid #334155; border-radius: 8px; }}
        th {{ background: #334155; color: #38bdf8; padding: 12px;
            text-align: left; font-size: 13px; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #334155; font-size: 14px; }}
        tr:last-child td {{ border-bottom: none; }}
        .links {{ margin-top: 20px; }}
        .links a {{ color: #38bdf8; margin-right: 16px; text-decoration: none; }}
        .links a:hover {{ text-decoration: underline; }}
        .refresh {{ color: #94a3b8; font-size: 12px; float: right; }}
    </style>
    <script>
        // Auto-refresh every 10 seconds
        setTimeout(function() {{ location.reload(); }}, 10000);
    </script>
</head>
<body>
    <h1>🛡️ SentinelOps-Lite Monitor</h1>
    <div class="refresh">Auto-refresh: 10s</div>
    <p class="subtitle">Real-time application &amp; agent monitoring status</p>

    <h2>📊 Application Stats</h2>
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Total Requests</div>
            <div class="stat-value">{app_status.get('total_requests', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Success Requests</div>
            <div class="stat-value good">{app_status.get('success_requests', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Failed Requests</div>
            <div class="stat-value bad">{app_status.get('failed_requests', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Exceptions</div>
            <div class="stat-value bad">{app_status.get('exceptions', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Uptime (s)</div>
            <div class="stat-value">{app_status.get('uptime_seconds', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg Request Time (s)</div>
            <div class="stat-value warn">{app_status.get('avg_request_time', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Active Sessions</div>
            <div class="stat-value">{app_status.get('active_sessions', 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Active Users</div>
            <div class="stat-value">{app_status.get('active_users', 0)}</div>
        </div>
    </div>

    <h2>🤖 Agent Status</h2>
    <table>
        <thead>
            <tr>
                <th>Agent</th>
                <th>Status</th>
                <th>Decision</th>
                <th>Stage</th>
                <th>Cloud</th>
                <th>AI Provider/Model</th>
                <th>Total Tokens</th>
                <th>API Requests</th>
                <th>Exec Time</th>
                <th>Last Run</th>
            </tr>
        </thead>
        <tbody>
            {agent_rows}
        </tbody>
    </table>

    <div class="links">
        <a href="/api/status">📋 JSON API Status</a>
        <a href="/agent/status">🤖 Agent JSON</a>
        <a href="/metrics">📈 Prometheus Metrics</a>
        <a href="/grafana/">📊 Grafana Dashboard</a>
        <a href="/health">❤️ Health Check</a>
    </div>
</body>
</html>
    """
    return Response(html, mimetype="text/html")


@application.route("/monitor/status", methods=["POST"])
def monitor_status():
    """
    Receives monitoring events from CI AI agents.
    Required:  agent_name, stage, status
    Optional:  cloud, provider, model, tokens, requests, decision, error

    Protected by X-Monitor-Token header (if MONITOR_TOKEN env var is set).
    """
    expected_token = os.getenv("MONITOR_TOKEN")
    if expected_token and request.headers.get("X-Monitor-Token") != expected_token:
        return jsonify(error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name", "unknown")).strip().lower()
    stage = str(data.get("stage", "unknown")).strip().lower()
    cloud = str(data.get("cloud", "unknown")).strip().lower()
    provider = str(data.get("provider", "gemini")).strip().lower()
    model = str(data.get("model", "unknown")).strip()
    status = str(data.get("status", "idle")).strip().lower()
    if status not in AGENT_STATES:
        status = "failed"
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

    for item in AGENT_STATES:
        agent_state.labels(**labels, state=item).set(1 if item == status else 0)
    for item in AGENT_DECISIONS:
        agent_last_decision.labels(**labels, decision=item).set(
            1 if item == decision else 0
        )

    agent_model_info.labels(**labels).info({
        "provider": provider,
        "model": model,
    })
    agent_api_key_count.labels(**labels, provider=provider).set(api_key_count)
    agent_last_run_timestamp_seconds.labels(**labels).set(time.time())

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
# Active session / user helpers
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
