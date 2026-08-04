"""
agent/monitor_client.py
Shared helper for pipeline agents to POST metrics to /monitor/status.
Import and call `report()` from test_agent.py, errors.py, final_agent.py.
"""
from __future__ import annotations
import os
import time
import sys
import requests


MONITOR_URL   = os.environ.get("MONITOR_URL",   "").rstrip("/")
MONITOR_TOKEN = os.environ.get("MONITOR_TOKEN", "")

# Fallback: if MONITOR_URL not set, try Beanstalk URL from another env var
if not MONITOR_URL:
    MONITOR_URL = os.environ.get("BEANSTALK_URL", "").rstrip("/")


def report(
    agent_name: str,
    stage: str,
    *,
    state: str = "running",
    decision: str | None = None,
    status: str = "success",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    api_calls: int = 1,
    task_result: str | None = None,
    task_count: int = 1,
    execution_time_seconds: float = 0.0,
    api_response_time_seconds: float = 0.0,
    api_key_count: int = 0,
    cloud: str = "aws",
    provider: str | None = None,
    model:    str | None = None,
    fail_hard: bool = True,
) -> bool:
    """
    POST metrics to <MONITOR_URL>/monitor/status.
    Returns True on success, False on failure (raises if fail_hard=True).
    """
    if not MONITOR_URL:
        msg = "[monitor] MONITOR_URL not set — cannot report"
        print(msg)
        if fail_hard:
            raise RuntimeError(msg)
        return False

    if total_tokens is None:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    payload = {
        "agent_name":                agent_name,
        "stage":                     stage,
        "cloud":                     cloud,
        "state":                     state,
        "status":                    status,
        "prompt_tokens":             prompt_tokens,
        "completion_tokens":         completion_tokens,
        "total_tokens":              total_tokens,
        "api_calls":                 api_calls,
        "task_count":                task_count,
        "execution_time_seconds":    execution_time_seconds,
        "api_response_time_seconds": api_response_time_seconds,
        "api_key_count":             api_key_count,
    }
    if decision:    payload["decision"]    = decision
    if task_result: payload["task_result"] = task_result
    if provider:    payload["provider"]    = provider
    if model:       payload["model"]       = model

    url = f"{MONITOR_URL}/monitor/status"
    headers = {"Content-Type": "application/json"}
    if MONITOR_TOKEN:
        headers["X-Monitor-Token"] = MONITOR_TOKEN

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"[monitor] POST {url} → {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[monitor] POST failed for agent={agent_name}: {e}")
        if fail_hard:
            raise
        return False







def send_agent_status(
    *,
    agent_name: str,
    stage: str,
    status: str,
    decision: str = "none",
    provider: str = "unknown",
    model: str = "unknown",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    requests_count: int = 0,
    api_key_count: int = 0,
    execution_time_seconds: float = 0.0,
    api_response_time_seconds: float = 0.0,
    error: str = "",
) -> bool:
    """POST one agent's real execution totals.

    The function returns False instead of breaking a deployment when monitoring
    is unavailable, but logs the reason so missing Grafana data is diagnosable.
    """
    url = os.getenv("MONITOR_API_URL", "").strip()
    if not url:
        print(
            f"[monitor] MONITOR_API_URL is not set; {agent_name} was not reported",
            file=sys.stderr,
        )
        return False

    payload = {
        "agent_name": agent_name,
        "stage": stage,
        "cloud": os.getenv("TARGET_CLOUD", os.getenv("ENVIRONMENT", "unknown")),
        "status": status,
        "decision": decision,
        "provider": provider,
        "model": model,
        "prompt_tokens": max(0, int(prompt_tokens or 0)),
        "completion_tokens": max(0, int(completion_tokens or 0)),
        "total_tokens": max(0, int(total_tokens or 0)),
        # Send both field names for compatibility with old receivers.
        "requests": max(0, int(requests_count or 0)),
        "requests_count": max(0, int(requests_count or 0)),
        "api_key_count": max(0, int(api_key_count or 0)),
        "execution_time_seconds": max(0.0, float(execution_time_seconds or 0)),
        "api_response_time_seconds": max(0.0, float(api_response_time_seconds or 0)),
    }
    if error:
        payload["error"] = str(error)[:500]

    headers = {"Content-Type": "application/json"}
    token = os.getenv("MONITOR_TOKEN", "").strip()
    if token:
        headers["X-Monitor-Token"] = token

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        print(
            f"[monitor] reported agent={agent_name} stage={stage} "
            f"status={status} tokens={payload['total_tokens']} "
            f"requests={payload['requests']}",
            file=sys.stderr,
        )
        return True
    except requests.RequestException as exc:
        print(
            f"[monitor] POST failed for agent={agent_name}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return False
