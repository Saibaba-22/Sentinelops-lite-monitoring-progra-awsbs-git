"""SentinelOps-Lite Flask application and AI-agent monitor receiver."""

from __future__ import annotations

import html
import os
import time
from typing import Any

from flask import Flask, Response, jsonify, redirect, request, url_for
from werkzeug.exceptions import HTTPException

from monitoring import agent_state as agent_state_store
from monitoring import collectors
from monitoring.metrics import (
    AGENT_DECISIONS,
    AGENT_STATES,
    APP_STATS,
    CONTENT_TYPE_LATEST,
    agent_api_calls_total,
    agent_api_key_count,
    agent_api_response_time_seconds,
    agent_completion_tokens_total,
    agent_execution_duration_seconds,
    agent_execution_time_seconds,
    agent_last_decision,
    agent_last_run_timestamp_seconds,
    agent_model_info,
    agent_prompt_tokens_total,
    agent_state,
    agent_tasks_total,
    agent_token_usage_total,
    app_active_sessions,
    app_active_users,
    app_errors_total,
    app_exceptions_total,
    app_request_duration_seconds,
    app_requests_total,
    generate_latest,
    http_status_codes_total,
    start_metrics_updater,
    update_metrics,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
application = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
)
application.config.update(ACTIVE_SESSIONS=0, ACTIVE_USERS=0, JSON_SORT_KEYS=False)

KNOWN_AGENTS = ("test_agent", "errors_agent", "final_agent")
STAGE_AGENT_MAP = {
    "pre_deploy": "test_agent",
    "pre-deploy": "test_agent",
    "deploy": "errors_agent",
    "during_deploy": "errors_agent",
    "during-deploy": "errors_agent",
    "post_deploy": "final_agent",
    "post-deploy": "final_agent",
}


@application.before_request
def _start_timer() -> None:
    request._start_time = time.perf_counter()


@application.after_request
def _record_metrics(response):
    # Prometheus scrapes should not increment the application's request counters.
    if request.path == "/metrics":
        return response

    duration = time.perf_counter() - getattr(request, "_start_time", time.perf_counter())
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
        APP_STATS["exceptions"] += 1
        APP_STATS["failed_requests"] += 1
    elif response.status_code < 400:
        APP_STATS["success_requests"] += 1
    else:
        APP_STATS["failed_requests"] += 1
    return response


@application.errorhandler(Exception)
def _handle_exception(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code
    app_exceptions_total.inc()
    APP_STATS["exceptions"] += 1
    application.logger.exception("Unhandled application exception")
    return jsonify(error="internal server error"), 500


@application.get("/metrics")
def metrics():
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


@application.get("/health")
def health():
    """HTML health response kept compatible with the existing test suite."""
    return Response(
        "<html><body><strong>healthy</strong></body></html>",
        mimetype="text/html",
    )


@application.get("/prometheus")
def prometheus_redirect():
    return redirect("/prometheus/", code=308)


@application.get("/api/status")
def api_status():
    return jsonify(collectors.build_status())


@application.get("/agent/status")
def agent_status():
    state_data = agent_state_store.load()
    agents = state_data.get("agents", {})
    latest = max(
        agents.values(),
        key=lambda item: str(item.get("last_run") or ""),
        default={},
    )
    latest_status = latest or {}
    return jsonify(
        status=str(latest_status.get("status", state_data.get("status", "idle"))).capitalize(),
        decision=latest_status.get("decision", state_data.get("decision", "none")),
        provider=latest_status.get("provider", "gemini"),
        model=latest_status.get("model", "gemini-2.5-flash"),
        prompt_tokens=latest_status.get("prompt_tokens", 0),
        completion_tokens=latest_status.get("completion_tokens", 0),
        total_tokens=latest_status.get("total_tokens", 0),
        tokens=latest_status.get("total_tokens", 0),
        requests=latest_status.get("requests", 0),
        api_key_count=latest_status.get("api_key_count", 0),
        api_keys=latest_status.get("api_key_count", 0),
        last_run=latest_status.get("last_run"),
        execution_time_seconds=latest_status.get("execution_time_seconds", 0),
        agents=agents,
    )


@application.get("/api/agents")
def api_agents():
    """Return every known agent, including agents that have not reported yet."""
    state = agent_state_store.load()
    agents = state.setdefault("agents", {})
    for name in KNOWN_AGENTS:
        agents.setdefault(
            name,
            {
                "agent_name": name,
                "status": "idle",
                "decision": "none",
                "stage": "unknown",
                "cloud": "unknown",
                "provider": "unknown",
                "model": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "requests": 0,
                "api_key_count": 0,
                "execution_time_seconds": 0,
                "last_run": None,
            },
        )
    return jsonify(agents=agents)


def _normalise_agent_name(data: dict[str, Any], stage: str) -> str:
    supplied = (
        data.get("agent_name")
        or request.headers.get("X-Agent-Name")
        or os.getenv("AGENT_NAME")
        or STAGE_AGENT_MAP.get(stage)
        or "unknown_agent"
    )
    return str(supplied).strip().lower().replace(" ", "_")[:80]


def _non_negative(value: Any, converter, default=0):
    try:
        return max(default, converter(value))
    except (TypeError, ValueError):
        return default


def _set_agent_metrics(
    *,
    agent_name: str,
    stage: str,
    cloud: str,
    provider: str,
    model: str,
    status: str,
    decision: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    requests_count: int,
    api_key_count: int,
    execution_time: float,
    response_time: float,
) -> None:
    labels = {"agent_name": agent_name, "stage": stage, "cloud": cloud}

    for item in AGENT_STATES:
        agent_state.labels(**labels, state=item).set(float(item == status))
    for item in AGENT_DECISIONS:
        agent_last_decision.labels(**labels, decision=item).set(float(item == decision))

    agent_model_info.labels(**labels).info({"provider": provider, "model": model})
    agent_api_key_count.labels(**labels, provider=provider).set(api_key_count)
    agent_last_run_timestamp_seconds.labels(**labels).set(time.time())

    if requests_count:
        agent_api_calls_total.labels(
            **labels,
            provider=provider,
            model=model,
            status="failed" if status == "failed" else "success",
        ).inc(requests_count)
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
        result = "approved" if status in ("approved", "healthy") else status
        agent_tasks_total.labels(**labels, result=result).inc()
        agent_execution_time_seconds.labels(**labels).set(execution_time)
        agent_execution_duration_seconds.labels(**labels).observe(execution_time)
        if response_time:
            agent_api_response_time_seconds.labels(
                **labels, provider=provider, model=model
            ).observe(response_time)


@application.post("/monitor/status")
def monitor_status_post():
    """Receive and persist one status event from a CI agent."""
    expected_token = os.getenv("MONITOR_TOKEN", "")
    supplied_token = request.headers.get("X-Monitor-Token", "")
    if expected_token and supplied_token != expected_token:
        return jsonify(ok=False, error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    stage = str(
        data.get("stage")
        or request.headers.get("X-Agent-Stage")
        or "unknown"
    ).strip().lower()[:80]
    agent_name = _normalise_agent_name(data, stage)
    cloud = str(
        data.get("cloud")
        or request.headers.get("X-Cloud")
        or os.getenv("TARGET_CLOUD")
        or os.getenv("ENVIRONMENT")
        or "unknown"
    ).strip().lower()[:40]
    provider = str(data.get("provider", "unknown")).strip().lower()[:40]
    model = str(data.get("model", "unknown")).strip()[:120]

    status = str(data.get("status", "idle")).strip().lower()
    if status not in AGENT_STATES:
        status = "failed"
    decision = str(data.get("decision", status)).strip().lower()
    if decision not in AGENT_DECISIONS:
        decision = "none"

    prompt_tokens = _non_negative(data.get("prompt_tokens", 0), int)
    completion_tokens = _non_negative(data.get("completion_tokens", 0), int)
    total_tokens = _non_negative(
        data.get("total_tokens", prompt_tokens + completion_tokens), int
    )
    # Accept both names so old and new monitor clients work.
    requests_count = _non_negative(
        data.get("requests", data.get("requests_count", 0)), int
    )
    api_key_count = _non_negative(data.get("api_key_count", 0), int)
    execution_time = _non_negative(
        data.get("execution_time_seconds", 0), float
    )
    response_time = _non_negative(
        data.get("api_response_time_seconds", 0), float
    )

    _set_agent_metrics(
        agent_name=agent_name,
        stage=stage,
        cloud=cloud,
        provider=provider,
        model=model,
        status=status,
        decision=decision,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        requests_count=requests_count,
        api_key_count=api_key_count,
        execution_time=execution_time,
        response_time=response_time,
    )

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
        "requests": requests_count,
        "api_key_count": api_key_count,
        "execution_time_seconds": execution_time,
        "api_response_time_seconds": response_time,
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    agent_state_store.save(stored)

    return jsonify(
        ok=True,
        agent=agent_name,
        stage=stage,
        cloud=cloud,
        status=status,
        decision=decision,
    )


@application.get("/monitor/status")
def monitor_status_get():
    state = agent_state_store.load()
    agents = state.setdefault("agents", {})
    for name in KNOWN_AGENTS:
        agents.setdefault(
            name,
            {
                "agent_name": name,
                "status": "idle",
                "decision": "none",
                "stage": "unknown",
                "cloud": "unknown",
                "provider": "unknown",
                "model": "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "requests": 0,
                "api_key_count": 0,
                "execution_time_seconds": 0,
                "last_run": None,
            },
        )

    app_status = collectors.build_status()["application"]
    rows = []
    for name, data in agents.items():
        safe = {key: html.escape(str(value)) for key, value in data.items()}
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(name)}</strong></td>"
            f"<td>{safe.get('status', 'idle')}</td>"
            f"<td>{safe.get('decision', 'none')}</td>"
            f"<td>{safe.get('stage', 'unknown')}</td>"
            f"<td>{safe.get('cloud', 'unknown')}</td>"
            f"<td>{safe.get('provider', 'unknown')} / {safe.get('model', 'unknown')}</td>"
            f"<td>{safe.get('total_tokens', '0')}</td>"
            f"<td>{safe.get('requests', '0')}</td>"
            f"<td>{safe.get('last_run', 'never')}</td>"
            "</tr>"
        )

    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentinelOps-Lite Monitor</title><meta http-equiv="refresh" content="10">
<style>
body{{font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:24px}}
h1{{color:#38bdf8}}table{{width:100%;border-collapse:collapse;background:#1e293b}}
th,td{{padding:10px;text-align:left;border-bottom:1px solid #334155}}
th{{color:#38bdf8}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}
.card{{background:#1e293b;padding:16px;border-radius:8px}}.value{{font-size:24px;font-weight:700}}
a{{color:#38bdf8;margin-right:14px}}
</style></head><body>
<h1>SentinelOps-Lite Monitor</h1><p>Refreshes every 10 seconds.</p>
<div class="grid">
<div class="card">Requests<div class="value">{app_status.get('total_requests', 0)}</div></div>
<div class="card">Success<div class="value">{app_status.get('success_requests', 0)}</div></div>
<div class="card">Failed<div class="value">{app_status.get('failed_requests', 0)}</div></div>
<div class="card">Exceptions<div class="value">{app_status.get('exceptions', 0)}</div></div>
</div>
<h2>AI agent status</h2>
<table><thead><tr><th>Agent</th><th>Status</th><th>Decision</th><th>Stage</th><th>Cloud</th><th>Provider / Model</th><th>Tokens</th><th>Requests</th><th>Last run</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p><a href="/api/agents">All agents JSON</a><a href="/agent/status">Latest agent JSON</a><a href="/metrics">Prometheus metrics</a><a href="/grafana/">Grafana</a><a href="/health">Health</a></p>
</body></html>"""
    return Response(page, mimetype="text/html")


@application.get("/dashboard")
def dashboard():
    return redirect(url_for("monitor_status_get"))


def set_active_counts(sessions: int, users: int) -> None:
    application.config["ACTIVE_SESSIONS"] = sessions
    application.config["ACTIVE_USERS"] = users
    app_active_sessions.set(sessions)
    app_active_users.set(users)


def _restore_agent_metrics() -> None:
    """Restore persisted agent state into the fresh Prometheus registry.

    The HTML monitor reads logs/agent_stats.json directly, but Prometheus
    metrics are in memory. Without this restore, /monitor/status can show
    data while Grafana remains empty after a container restart.
    """
    try:
        stored = agent_state_store.load()
        agents = stored.get("agents", {})
        for name in KNOWN_AGENTS:
            data = agents.get(name, {})
            stage = str(data.get("stage") or "unknown")
            cloud = str(data.get("cloud") or "unknown")
            provider = str(data.get("provider") or "unknown")
            model = str(data.get("model") or "unknown")
            status = str(data.get("status") or "idle").lower()
            decision = str(data.get("decision") or "none").lower()
            if status not in AGENT_STATES:
                status = "idle"
            if decision not in AGENT_DECISIONS:
                decision = "none"
            labels = {"agent_name": name, "stage": stage, "cloud": cloud}

            for item in AGENT_STATES:
                agent_state.labels(**labels, state=item).set(float(item == status))
            for item in AGENT_DECISIONS:
                agent_last_decision.labels(**labels, decision=item).set(float(item == decision))
            agent_model_info.labels(**labels).info({"provider": provider, "model": model})
            agent_api_key_count.labels(
                **labels, provider=provider
            ).set(_non_negative(data.get("api_key_count", 0), int))

            last_run = data.get("last_run")
            if last_run:
                try:
                    from calendar import timegm
                    from datetime import datetime
                    parsed = datetime.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ")
                    agent_last_run_timestamp_seconds.labels(**labels).set(timegm(parsed.timetuple()))
                except (TypeError, ValueError, OverflowError):
                    pass

            provider_labels = {**labels, "provider": provider, "model": model}
            agent_prompt_tokens_total.labels(**provider_labels)._value.set(
                _non_negative(data.get("prompt_tokens", 0), int)
            )
            agent_completion_tokens_total.labels(**provider_labels)._value.set(
                _non_negative(data.get("completion_tokens", 0), int)
            )
            agent_token_usage_total.labels(**provider_labels)._value.set(
                _non_negative(data.get("total_tokens", 0), int)
            )
            request_count = _non_negative(data.get("requests", 0), int)
            if request_count:
                agent_api_calls_total.labels(
                    **provider_labels,
                    status="failed" if status == "failed" else "success",
                )._value.set(request_count)
            agent_execution_time_seconds.labels(**labels).set(
                _non_negative(data.get("execution_time_seconds", 0), float)
            )
    except Exception:
        application.logger.exception("Could not restore persisted agent metrics")


_restore_agent_metrics()
update_metrics()
if os.getenv("DISABLE_METRICS_THREAD", "0") != "1":
    start_metrics_updater(interval=int(os.getenv("METRICS_INTERVAL", "5")))
