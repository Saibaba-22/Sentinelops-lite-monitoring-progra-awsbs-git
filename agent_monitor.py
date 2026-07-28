"""SentinelOps-Lite Flask application and modern AI-agent monitor."""

from __future__ import annotations

import html
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests
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

AI_RPM_LIMIT = int(os.getenv("AI_RPM_LIMIT", "15"))
AI_TPM_LIMIT = int(os.getenv("AI_TPM_LIMIT", "250000"))
AI_RPD_LIMIT = int(os.getenv("AI_RPD_LIMIT", "500"))

# ---------------------------------------------------------------------------
# In-memory rate tracking for accurate RPM / TPM / RPD calculation.
#
# Prometheus increase() needs 2+ scrapes inside the window and breaks on
# counter resets (app restarts).  By recording every POST locally we can
# compute exact rates regardless of scrape cadence or restarts.
# ---------------------------------------------------------------------------
# Each entry: (epoch_seconds, requests_count, tokens_count)
_rate_history: dict[str, list[tuple[float, int, int]]] = defaultdict(list)
_RATE_HISTORY_MAX_AGE = 86400  # keep 24 h of data per agent


def _record_rate(agent_name: str, req_count: int, token_count: int) -> None:
    """Record a POST for in-memory rate calculation."""
    now = time.time()
    bucket = _rate_history[agent_name]
    bucket.append((now, max(0, req_count), max(0, token_count)))
    # prune old entries
    cutoff = now - _RATE_HISTORY_MAX_AGE
    _rate_history[agent_name] = [e for e in bucket if e[0] > cutoff]


def _calc_rates(agent_name: str) -> dict[str, float]:
    """Return {rpm, tpm, rph, rpd, tok_day} from in-memory history.
    
    Calculates average rates over sliding windows:
    - RPM: average requests per minute over last 5 minutes
    - TPM: average tokens per minute over last 5 minutes
    - RPH: requests in last hour
    - RPD: requests in last 24 hours
    - tok_day: tokens in last 24 hours
    """
    now = time.time()
    entries = _rate_history.get(agent_name, [])
    
    # RPM/TPM: average over last 5 minutes (300 seconds)
    recent_5min = [(t, r, tok) for t, r, tok in entries if t > now - 300]
    if recent_5min:
        rpm = sum(r for _, r, _ in recent_5min) / 5.0  # average per minute
        tpm = sum(tok for _, _, tok in recent_5min) / 5.0
    else:
        rpm = 0.0
        tpm = 0.0
    
    # RPH: requests in last hour
    rph = sum(r for t, r, _ in entries if t > now - 3600)
    
    # RPD: requests in last 24 hours
    rpd = sum(r for t, r, _ in entries if t > now - 86400)
    
    # Tokens per day
    tok_day = sum(tok for t, _, tok in entries if t > now - 86400)
    
    return {"rpm": rpm, "tpm": tpm, "rph": rph, "rpd": rpd, "tok_day": tok_day}


def _prometheus_base_url() -> str:
    return os.getenv(
        "PROMETHEUS_URL", "http://prometheus:9090/prometheus"
    ).rstrip("/")


def _prom_query(query: str) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            f"{_prometheus_base_url()}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success":
            return []
        return body.get("data", {}).get("result", []) or []
    except (requests.RequestException, ValueError, TypeError):
        return []


def _prom_range(query: str) -> dict[str, list[float]]:
    """Return six-hour agent series for the small SVG sparklines."""
    end = time.time()
    start = end - 6 * 60 * 60
    try:
        response = requests.get(
            f"{_prometheus_base_url()}/api/v1/query_range",
            params={
                "query": query,
                "start": start,
                "end": end,
                "step": 300,
            },
            timeout=6,
        )
        response.raise_for_status()
        body = response.json()
        results = body.get("data", {}).get("result", []) or []
        output: dict[str, list[float]] = {}
        for item in results:
            name = item.get("metric", {}).get("agent_name")
            if not name:
                continue
            values = []
            for pair in item.get("values", []):
                try:
                    values.append(float(pair[1]))
                except (IndexError, TypeError, ValueError):
                    values.append(0.0)
            output[name] = values
        return output
    except (requests.RequestException, ValueError, TypeError):
        return {}


def _vector_by_agent(query: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in _prom_query(query):
        labels = item.get("metric", {})
        name = labels.get("agent_name")
        if not name:
            continue
        try:
            values[name] = float(item.get("value", [0, 0])[1])
        except (IndexError, TypeError, ValueError):
            values[name] = 0.0
    return values


def _states_by_agent() -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for item in _prom_query("agent_state == 1"):
        labels = item.get("metric", {})
        name = labels.get("agent_name")
        if name:
            values[name] = {
                "state": labels.get("state", "unknown"),
                "stage": labels.get("stage", "—"),
                "cloud": labels.get("cloud", "—"),
            }
    return values


def _models_by_agent() -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for item in _prom_query("agent_model_info"):
        labels = item.get("metric", {})
        name = labels.get("agent_name")
        if name:
            values[name] = {
                "provider": labels.get("provider", "—"),
                "model": labels.get("model", "—"),
                "stage": labels.get("stage", "—"),
                "cloud": labels.get("cloud", "—"),
            }
    return values


def _load_state() -> dict[str, Any]:
    try:
        path = os.getenv(
            "AGENT_STATE_FILE", os.path.join(BASE_DIR, "logs", "agent_stats.json")
        )
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _safe_number(value: Any, converter=float, default=0):
    try:
        return max(default, converter(value))
    except (TypeError, ValueError):
        return default


def _agent_snapshot() -> tuple[list[dict[str, Any]], bool]:
    persisted = _load_state().get("agents", {})
    if not isinstance(persisted, dict):
        persisted = {}

    total_tokens = _vector_by_agent(
        "sum by (agent_name) (agent_token_usage_total)"
    )
    prompt_tokens = _vector_by_agent(
        "sum by (agent_name) (agent_prompt_tokens_total)"
    )
    completion_tokens = _vector_by_agent(
        "sum by (agent_name) (agent_completion_tokens_total)"
    )
    total_requests = _vector_by_agent(
        "sum by (agent_name) (agent_api_calls_total)"
    )
    # Prometheus-based rates (may be 0 after restarts or with sparse scrapes)
    prom_requests_minute = _vector_by_agent(
        "sum by (agent_name) (increase(agent_api_calls_total[1m]))"
    )
    prom_tokens_minute = _vector_by_agent(
        "sum by (agent_name) (increase(agent_token_usage_total[1m]))"
    )
    prom_requests_hour = _vector_by_agent(
        "sum by (agent_name) (increase(agent_api_calls_total[1h]))"
    )
    prom_requests_day = _vector_by_agent(
        "sum by (agent_name) (increase(agent_api_calls_total[24h]))"
    )
    prom_tokens_day = _vector_by_agent(
        "sum by (agent_name) (increase(agent_token_usage_total[24h]))"
    )
    last_runs = _vector_by_agent(
        "max by (agent_name) (agent_last_run_timestamp_seconds)"
    )
    states = _states_by_agent()
    models = _models_by_agent()
    history = _prom_range(
        "sum by (agent_name) (rate(agent_api_calls_total[5m])) * 60"
    )

    discovered = set(KNOWN_AGENTS)
    discovered.update(persisted.keys())
    discovered.update(total_tokens.keys())
    discovered.update(total_requests.keys())
    discovered.update(states.keys())

    agents = []
    for name in sorted(discovered):
        saved = persisted.get(name, {})
        if not isinstance(saved, dict):
            saved = {}
        model = models.get(name, {})
        state_info = states.get(name, {})
        has_prometheus_data = bool(
            name in states or name in total_tokens or name in total_requests
        )
        last_run: Any = last_runs.get(name, 0)
        if not last_run:
            last_run = saved.get("last_run")

        total_request_value = round(
            total_requests.get(name, saved.get("requests", 0))
        )
        total_token_value = round(
            total_tokens.get(name, saved.get("total_tokens", 0))
        )

        # ------------------------------------------------------------------
        # Rate calculation: prefer in-memory rates (accurate, restart-safe),
        # fall back to Prometheus increase(), then to persisted estimates.
        # ------------------------------------------------------------------
        mem_rates = _calc_rates(name)

        # Compute last_run epoch for fallback estimation
        last_epoch = _safe_number(saved.get("last_run_epoch", 0), float)
        if not last_epoch:
            # Try Prometheus timestamp
            prom_epoch = last_runs.get(name, 0)
            if prom_epoch:
                last_epoch = float(prom_epoch)
        if not last_epoch and isinstance(last_run, str) and last_run:
            try:
                last_epoch = datetime.strptime(
                    last_run, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                last_epoch = 0
        age = max(0, time.time() - last_epoch) if last_epoch else 0

        # --- RPM (requests per minute) ---
        # Priority: persisted observed rate > in-memory > prometheus > estimate
        if saved.get("observed_rpm", 0) > 0 and 0 < age <= 86400:
            # Use last observed rate (persisted across restarts, stable display)
            minute_value = int(saved["observed_rpm"])
        elif mem_rates["rpm"] >= 0.5:
            minute_value = round(mem_rates["rpm"])
        elif round(prom_requests_minute.get(name, 0)) > 0:
            minute_value = round(prom_requests_minute.get(name, 0))
        elif total_request_value > 0 and 0 < age <= 300:
            # Agent ran very recently: use its request count as the RPM
            minute_value = max(1, total_request_value)
        else:
            minute_value = 0

        # --- TPM (tokens per minute) ---
        if saved.get("observed_tpm", 0) > 0 and 0 < age <= 86400:
            # Use last observed rate (persisted across restarts, stable display)
            token_minute_value = int(saved["observed_tpm"])
        elif mem_rates["tpm"] >= 0.5:
            token_minute_value = round(mem_rates["tpm"])
        elif round(prom_tokens_minute.get(name, 0)) > 0:
            token_minute_value = round(prom_tokens_minute.get(name, 0))
        elif total_token_value > 0 and 0 < age <= 300:
            token_minute_value = max(1, total_token_value)
        else:
            token_minute_value = 0

        # --- Requests per hour ---
        if mem_rates["rph"] > 0:
            hour_value = round(mem_rates["rph"])
        elif round(prom_requests_hour.get(name, 0)) > 0:
            hour_value = round(prom_requests_hour.get(name, 0))
        elif total_request_value > 0 and 0 < age <= 3600:
            hour_value = total_request_value
        else:
            hour_value = 0

        # --- Requests per day ---
        if mem_rates["rpd"] > 0:
            day_value = round(mem_rates["rpd"])
        elif round(prom_requests_day.get(name, 0)) > 0:
            day_value = round(prom_requests_day.get(name, 0))
        elif total_request_value > 0 and 0 < age <= 86400:
            day_value = total_request_value
        else:
            day_value = 0

        # --- Tokens per day ---
        if mem_rates["tok_day"] > 0:
            tokens_day_value = round(mem_rates["tok_day"])
        elif round(prom_tokens_day.get(name, 0)) > 0:
            tokens_day_value = round(prom_tokens_day.get(name, 0))
        elif total_token_value > 0 and 0 < age <= 86400:
            tokens_day_value = total_token_value
        else:
            tokens_day_value = 0

        # Render the raw epoch (from Prometheus) as a human-readable timestamp.
        if isinstance(last_run, (int, float)) and last_run:
            last_run_display = datetime.fromtimestamp(
                float(last_run), tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            last_run_display = last_run or None

        reported = has_prometheus_data or bool(saved.get("last_run"))
        agents.append(
            {
                "agent_name": name,
                "status": state_info.get("state", saved.get("status", "not reported"))
                if reported else "not reported",
                "decision": saved.get("decision", "none"),
                "stage": state_info.get("stage", model.get("stage", saved.get("stage", "—")))
                if reported else "—",
                "cloud": state_info.get("cloud", model.get("cloud", saved.get("cloud", "—")))
                if reported else "—",
                "provider": model.get("provider", saved.get("provider", "—"))
                if reported else "—",
                "model": model.get("model", saved.get("model", "—"))
                if reported else "—",
                "prompt_tokens": round(prompt_tokens.get(name, saved.get("prompt_tokens", 0))),
                "completion_tokens": round(completion_tokens.get(name, saved.get("completion_tokens", 0))),
                "total_tokens": total_token_value,
                "requests_total": total_request_value,
                "requests_minute": minute_value,
                "tokens_minute": token_minute_value,
                "requests_hour": hour_value,
                "requests_day": day_value,
                "tokens_day": tokens_day_value,
                "rpm_limit": AI_RPM_LIMIT,
                "tpm_limit": AI_TPM_LIMIT,
                "rpd_limit": AI_RPD_LIMIT,
                "last_run": last_run_display,
                "has_prometheus_data": has_prometheus_data,
                "demo": bool(saved.get("demo")),
                "request_history": history.get(name, []),
            }
        )

    return agents, bool(_prom_query("up"))


@application.before_request
def _start_timer() -> None:
    request._start_time = time.perf_counter()


@application.after_request
def _record_metrics(response):
    if request.path == "/metrics":
        return response
    duration = time.perf_counter() - getattr(
        request, "_start_time", time.perf_counter()
    )
    method, endpoint, status = request.method, request.path, str(response.status_code)
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


@application.get("/api/agent-metrics")
def api_agent_metrics():
    agents, connected = _agent_snapshot()
    return jsonify(
        generated_at=datetime.now(timezone.utc).isoformat(),
        prometheus_url=_prometheus_base_url(),
        prometheus_connected=connected,
        agents=agents,
    )


@application.get("/api/agents")
def api_agents():
    agents, connected = _agent_snapshot()
    return jsonify(
        generated_at=datetime.now(timezone.utc).isoformat(),
        prometheus_connected=connected,
        agents=agents,
    )


@application.get("/agent/status")
def agent_status():
    state = agent_state_store.load()
    agents = state.get("agents", {})
    latest = max(
        agents.values(), key=lambda item: str(item.get("last_run") or ""), default={}
    )
    return jsonify(
        status=str(latest.get("status", state.get("status", "idle"))).capitalize(),
        decision=latest.get("decision", state.get("decision", "none")),
        provider=latest.get("provider", "gemini"),
        model=latest.get("model", "gemini-2.5-flash"),
        prompt_tokens=latest.get("prompt_tokens", 0),
        completion_tokens=latest.get("completion_tokens", 0),
        total_tokens=latest.get("total_tokens", 0),
        tokens=latest.get("total_tokens", 0),
        requests=latest.get("requests", 0),
        api_key_count=latest.get("api_key_count", 0),
        last_run=latest.get("last_run"),
        execution_time_seconds=latest.get("execution_time_seconds", 0),
        agents=agents,
    )


def _normalise_agent_name(data: dict[str, Any], stage: str) -> str:
    value = (
        data.get("agent_name")
        or request.headers.get("X-Agent-Name")
        or os.getenv("AGENT_NAME")
        or STAGE_AGENT_MAP.get(stage)
        or "unknown_agent"
    )
    return str(value).strip().lower().replace(" ", "_")[:80]


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
    expected = os.getenv("MONITOR_TOKEN", "")
    if expected and request.headers.get("X-Monitor-Token", "") != expected:
        return jsonify(ok=False, error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    stage = str(
        data.get("stage") or request.headers.get("X-Agent-Stage") or "unknown"
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
    prompt = _safe_number(data.get("prompt_tokens", 0), int)
    completion = _safe_number(data.get("completion_tokens", 0), int)
    total = _safe_number(data.get("total_tokens", prompt + completion), int)
    requests_count = _safe_number(
        data.get("requests", data.get("requests_count", 0)), int
    )
    keys = _safe_number(data.get("api_key_count", 0), int)
    execution = _safe_number(data.get("execution_time_seconds", 0), float)
    response_time = _safe_number(
        data.get("api_response_time_seconds", 0), float
    )

    # Record for in-memory rate tracking BEFORE setting Prometheus metrics
    _record_rate(agent_name, requests_count, total)

    # Calculate observed rates at this moment for persistent display.
    # We use the actual request/token counts from this reporting cycle
    # (not burst rates) because quota monitoring cares about how much
    # was consumed, not how fast it was consumed.
    mem_rates_now = _calc_rates(agent_name)
    observed_rpm = max(
        round(mem_rates_now["rpm"]),
        requests_count,  # requests in this reporting cycle
    )
    observed_tpm = max(
        round(mem_rates_now["tpm"]),
        total,  # tokens in this reporting cycle
    )

    _set_agent_metrics(
        agent_name=agent_name,
        stage=stage,
        cloud=cloud,
        provider=provider,
        model=model,
        status=status,
        decision=decision,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        requests_count=requests_count,
        api_key_count=keys,
        execution_time=execution,
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
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "requests": requests_count,
        "api_key_count": keys,
        "execution_time_seconds": execution,
        "api_response_time_seconds": response_time,
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_run_epoch": time.time(),
        "observed_rpm": observed_rpm,
        "observed_tpm": observed_tpm,
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
    page = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentinelOps AI Agent Monitor</title>
<style>
:root{--bg:#070b18;--panel:#11182b;--panel2:#17213a;--line:#263452;--text:#edf4ff;--muted:#8ea0c0;--blue:#56b4ff;--cyan:#53e0d0;--green:#4ade80;--amber:#fbbf24;--red:#fb7185}
*{box-sizing:border-box}body{margin:0;min-height:100vh;font:14px/1.5 system-ui,sans-serif;color:var(--text);background:radial-gradient(circle at 10% 0%,#143159 0,transparent 35%),var(--bg)}.wrap{max-width:1500px;margin:auto;padding:30px}.top{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:25px}h1{margin:0;font-size:clamp(26px,4vw,44px);letter-spacing:-.05em}.sub,.meta{color:var(--muted)}.live{display:flex;gap:9px;align-items:center;color:var(--muted)}.dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 15px var(--green)}.dot.off{background:var(--red);box-shadow:0 0 15px var(--red)}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}.card{background:linear-gradient(145deg,#151f38,#0e1528);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 16px 45px #0005}.label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em}.num{font-size:32px;font-weight:800;margin-top:4px}.agents{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:16px}.agent{position:relative;overflow:hidden}.agent:before{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--blue),var(--cyan))}.head{display:flex;justify-content:space-between;gap:12px}.name{font-size:21px;font-weight:750}.badge{border:1px solid #ffffff25;border-radius:999px;padding:4px 10px;color:var(--cyan);font-size:11px;text-transform:uppercase}.badge.not{color:var(--muted)}.details{margin-top:4px;color:var(--muted);font-size:12px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:18px}.metric{background:#0a1020aa;border:1px solid #ffffff0d;border-radius:12px;padding:11px}.metric span{display:block;color:var(--muted);font-size:10px}.metric b{display:block;font-size:19px;margin-top:3px}.quota-title{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em;margin-top:18px}.quota-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:8px}.quota{background:#0a1020aa;border:1px solid #ffffff0d;border-radius:12px;padding:12px}.quota span{display:block;color:var(--muted);font-size:11px}.quota strong{display:block;color:var(--cyan);font-size:19px;margin-top:3px}.visual{display:grid;grid-template-columns:150px 1fr;gap:20px;align-items:center;margin-top:17px}.semi{height:76px;width:150px;overflow:hidden;position:relative}.semi:before{content:"";position:absolute;width:150px;height:150px;border-radius:50%;background:conic-gradient(var(--blue) calc(var(--pct)*1%),#263452 0);transform:rotate(-90deg)}.semi:after{content:"";position:absolute;left:20px;top:20px;width:110px;height:110px;border-radius:50%;background:var(--panel)}.semi strong{position:absolute;z-index:2;left:0;right:0;top:32px;text-align:center;font-size:18px}.bars{display:grid;gap:8px}.barrow{display:grid;grid-template-columns:78px 1fr 50px;gap:7px;align-items:center;color:var(--muted);font-size:11px}.bar{height:7px;background:#263452;border-radius:20px;overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--cyan));border-radius:20px}.spark{margin-top:17px;background:#0a1020aa;border:1px solid #ffffff0d;border-radius:12px;padding:8px}.notice{margin:15px 0;padding:13px 16px;border:1px solid #fbbf2435;background:#fbbf2410;border-radius:12px;color:#fcd879}.empty{text-align:center;color:var(--muted);padding:35px}.footer{color:var(--muted);margin-top:20px;font-size:12px}@media(max-width:800px){.wrap{padding:18px}.top{display:block}.live{margin-top:15px}.summary{grid-template-columns:repeat(2,1fr)}.agents{grid-template-columns:1fr}}@media(max-width:470px){.metrics{grid-template-columns:repeat(2,1fr)}.visual{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<header class="top"><div><h1>SentinelOps <span style="color:var(--blue)">AI Agents</span></h1><div class="sub">Real Prometheus totals, requests and 24-hour activity</div></div><div class="live"><i id="dot" class="dot"></i><span id="connection">Connecting...</span></div></header>
<section class="summary"><div class="card"><div class="label">Configured agents</div><div id="configured" class="num">—</div></div><div class="card"><div class="label">Reporting agents</div><div id="agents" class="num">—</div></div><div class="card"><div class="label">Total tokens</div><div id="tokens" class="num">—</div></div><div class="card"><div class="label">RPD total</div><div id="rpd" class="num">—</div></div></section>
<div id="notice" class="notice" hidden></div><section id="cards" class="agents"><div class="card empty">Loading real agent metrics...</div></section><div class="footer">Refreshes every 10 seconds · Source: Prometheus with persisted status fallback</div></div>
<script>
const put=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value};
const fmt=n=>Number(n||0).toLocaleString();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));


function spark(values){
  if(!values||values.length<2)return '<div class="meta">No request history yet</div>';
  let w=430,h=48,min=Math.min(...values),max=Math.max(...values),range=max-min||1;
  let pts=values.map((v,i)=>`${(i/(values.length-1))*w},${h-((v-min)/range)*h}`).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="48" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="#53e0d0" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}


function compact(n){
  n=Number(n||0);
  if(n>=1000000)return (n/1000000).toFixed(n>=10000000?0:2).replace(/\.00$/,'')+'M';
  if(n>=1000)return (n/1000).toFixed(n>=100000?0:2).replace(/\.00$/,'')+'K';
  return n.toLocaleString();
}


function card(a,maxDay,maxToken){
  let status=String(a.status||'not reported').toLowerCase(),
      rpdPct=a.rpd_limit?Math.min(100,(a.requests_day/a.rpd_limit)*100):0,
      tokPct=maxToken?Math.min(100,(a.total_tokens/maxToken)*100):0;
  return `<article class="card agent"><div class="head"><div><div class="name">${esc(a.agent_name)}</div><div class="details">${esc(a.provider)} · ${esc(a.model)} · ${esc(a.cloud)} · ${esc(a.stage)}</div></div><span class="badge ${a.has_prometheus_data?'':'not'}">${esc(status)}</span>${a.demo?'<span class="badge" style="color:#fbbf24;border-color:#fbbf2455;margin-left:6px">DEMO</span>':''}</div><div class="metrics"><div class="metric"><span>Total tokens</span><b>${compact(a.total_tokens)}</b></div><div class="metric"><span>Total requests</span><b>${compact(a.requests_total)}</b></div><div class="metric"><span>Last run</span><b style="font-size:12px">${esc(a.last_run||'—')}</b></div><div class="metric"><span>Prompt tokens</span><b>${compact(a.prompt_tokens)}</b></div><div class="metric"><span>Completion tokens</span><b>${compact(a.completion_tokens)}</b></div><div class="metric"><span>Tokens / day</span><b>${compact(a.tokens_day)}</b></div></div><div class="quota-title">Quota usage · current / limit</div><div class="quota-grid"><div class="quota"><span>RPM</span><strong>${compact(a.requests_minute)} / ${compact(a.rpm_limit)}</strong></div><div class="quota"><span>TPM</span><strong>${compact(a.tokens_minute)} / ${compact(a.tpm_limit)}</strong></div><div class="quota"><span>RPD</span><strong>${compact(a.requests_day)} / ${compact(a.rpd_limit)}</strong></div></div><div class="visual"><div class="semi" style="--pct:${rpdPct}"><strong>${compact(a.requests_day)} / ${compact(a.rpd_limit)}</strong></div><div class="bars"><div class="barrow"><span>RPM</span><div class="bar"><i style="width:${Math.min(100,(Number(a.requests_minute||0)/Math.max(1,Number(a.rpm_limit||1)))*100)}%"></i></div><b>${compact(a.requests_minute)}</b></div><div class="barrow"><span>TPM</span><div class="bar"><i style="width:${Math.min(100,(Number(a.tokens_minute||0)/Math.max(1,Number(a.tpm_limit||1)))*100)}%"></i></div><b>${compact(a.tokens_minute)}</b></div><div class="barrow"><span>RPD</span><div class="bar"><i style="width:${rpdPct}%"></i></div><b>${compact(a.requests_day)}</b></div></div></div><div class="spark">${spark(a.request_history)}</div><div class="meta" style="margin-top:12px">Decision: ${esc(a.decision)}</div></article>`;
}


async function refresh(){
  try{
    let r=await fetch('/api/agent-metrics',{cache:'no-store'}),
        d=await r.json(),
        list=d.agents||[],
        real=list.filter(a=>a.has_prometheus_data),
        maxDay=Math.max(0,...list.map(a=>Number(a.requests_day||0))),
        maxToken=Math.max(0,...list.map(a=>Number(a.total_tokens||0)));
    document.getElementById('dot')?.classList.toggle('off',!d.prometheus_connected);
    put('connection',d.prometheus_connected?'Prometheus connected':'Prometheus unavailable');
    put('configured',fmt(list.length));
    put('agents',fmt(real.length));
    put('tokens',fmt(list.reduce((n,a)=>n+Number(a.total_tokens||0),0)));
    put('rpm',fmt(list.reduce((n,a)=>n+Number(a.requests_minute||0),0)));
    put('rpd',fmt(list.reduce((n,a)=>n+Number(a.requests_day||0),0)));
    let n=document.getElementById('notice');
    n.hidden=d.prometheus_connected && real.length>0;
    if(!d.prometheus_connected)n.textContent='The app cannot reach Prometheus. Add the Prometheus ECS link and PROMETHEUS_URL to the app container.';
    else if(!real.length)n.textContent='Prometheus is connected, but no real AI-agent samples have been reported yet.';
    document.getElementById('cards').innerHTML=list.map(a=>card(a,maxDay,maxToken)).join('');
  }catch(e){
    document.getElementById('dot').classList.add('off');
    put('connection','Dashboard API unavailable');
    let n=document.getElementById('notice');
    if(n){n.hidden=false;n.textContent=String(e);}
  }
}
refresh();
setInterval(refresh,10000);
</script></body></html>"""
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
    """Restore real persisted reports into a fresh Prometheus registry.

    Only restores gauge-like metrics (state, decision, model info, timestamps).
    Counters are NOT restored via _value.set() because that causes Prometheus
    to see counter resets which breaks increase() calculations for RPM/TPM/RPD.
    Counter totals are preserved in the persisted JSON and displayed directly.
    """
    try:
        stored = agent_state_store.load()
        for name, data in stored.get("agents", {}).items():
            if not data.get("last_run"):
                continue
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
            agent_api_key_count.labels(**labels, provider=provider).set(
                _safe_number(data.get("api_key_count", 0), int)
            )
            agent_execution_time_seconds.labels(**labels).set(
                _safe_number(data.get("execution_time_seconds", 0), float)
            )
            # Restore last_run timestamp so dashboards show correct last-run time
            last_epoch = _safe_number(data.get("last_run_epoch", 0), float)
            if not last_epoch and data.get("last_run"):
                try:
                    last_epoch = datetime.strptime(
                        str(data["last_run"]), "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    last_epoch = time.time()
            agent_last_run_timestamp_seconds.labels(**labels).set(
                last_epoch if last_epoch else time.time()
            )
    except Exception:
        application.logger.exception("Could not restore agent metrics")


def _seed_demo_agents() -> None:
    """Seed known agents that have no real data with clearly-marked DEMO data.

    Disabled with SEED_DEMO_AGENTS=0. A real report (POST /monitor/status)
    overwrites the demo entry, so live data always wins once an agent reports.
    Only seeds an agent the very first time (when it is absent); on later
    restarts _restore_agent_metrics reloads the persisted demo values without
    re-incrementing counters.
    """
    if os.getenv("SEED_DEMO_AGENTS", "1") != "1":
        return
    profiles = {
        "test_agent": {
            "stage": "pre_deploy", "cloud": "aws", "provider": "gemini",
            "model": "gemini-2.5-flash", "status": "approved", "decision": "approved",
            "prompt_tokens": 820, "completion_tokens": 390, "total_tokens": 1210,
            "requests": 1, "api_key_count": 1,
            "execution_time_seconds": 1.9, "api_response_time_seconds": 1.4,
        },
        "errors_agent": {
            "stage": "deploy", "cloud": "gcp", "provider": "openai",
            "model": "gpt-4o-mini", "status": "approved", "decision": "approved",
            "prompt_tokens": 640, "completion_tokens": 120, "total_tokens": 760,
            "requests": 1, "api_key_count": 1,
            "execution_time_seconds": 2.2, "api_response_time_seconds": 1.6,
        },
        "final_agent": {
            "stage": "post_deploy", "cloud": "aws", "provider": "gemini",
            "model": "gemini-3.1-flash-lite", "status": "approved", "decision": "approved",
            "prompt_tokens": 1070, "completion_tokens": 478, "total_tokens": 1548,
            "requests": 1, "api_key_count": 1,
            "execution_time_seconds": 2.3, "api_response_time_seconds": 1.7,
        },
    }
    try:
        stored = agent_state_store.load()
        agents = stored.get("agents", {})
        if not isinstance(agents, dict):
            agents = {}
        changed = False
        for name in KNOWN_AGENTS:
            existing = agents.get(name)
            if isinstance(existing, dict) and existing.get("last_run"):
                continue  # already has data (real report or previously seeded)
            profile = profiles.get(name)
            if not profile:
                continue
            # Calculate observed rates for demo display:
            # Use the actual request/token counts (not burst rates)
            demo_rpm = max(1, profile["requests"])
            demo_tpm = max(1, profile["total_tokens"])
            agents[name] = {
                "agent_name": name,
                "stage": profile["stage"],
                "cloud": profile["cloud"],
                "provider": profile["provider"],
                "model": profile["model"],
                "status": profile["status"],
                "decision": profile["decision"],
                "prompt_tokens": profile["prompt_tokens"],
                "completion_tokens": profile["completion_tokens"],
                "total_tokens": profile["total_tokens"],
                "requests": profile["requests"],
                "api_key_count": profile["api_key_count"],
                "execution_time_seconds": profile["execution_time_seconds"],
                "api_response_time_seconds": profile["api_response_time_seconds"],
                "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "last_run_epoch": time.time(),
                "observed_rpm": demo_rpm,
                "observed_tpm": demo_tpm,
                "demo": True,
            }
            _set_agent_metrics(
                agent_name=name,
                stage=profile["stage"],
                cloud=profile["cloud"],
                provider=profile["provider"],
                model=profile["model"],
                status=profile["status"],
                decision=profile["decision"],
                prompt_tokens=profile["prompt_tokens"],
                completion_tokens=profile["completion_tokens"],
                total_tokens=profile["total_tokens"],
                requests_count=profile["requests"],
                api_key_count=profile["api_key_count"],
                execution_time=profile["execution_time_seconds"],
                response_time=profile["api_response_time_seconds"],
            )
            # Also record in in-memory rate tracker so demo agents show
            # non-zero RPM/TPM/RPD immediately after seeding
            _record_rate(name, profile["requests"], profile["total_tokens"])
            changed = True
        if changed:
            stored["agents"] = agents
            agent_state_store.save(stored)
            application.logger.info("Seeded DEMO data for agents with no real report")
    except Exception:
        application.logger.exception("Could not seed demo agents")


_restore_agent_metrics()
_seed_demo_agents()
update_metrics()
if os.getenv("DISABLE_METRICS_THREAD", "0") != "1":
    start_metrics_updater(interval=int(os.getenv("METRICS_INTERVAL", "5")))
