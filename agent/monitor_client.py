"""
agent/monitor_client.py
Shared helper for pipeline agents to POST metrics to /monitor/status.

Usage:
    from agent.monitor_client import report
    report(agent_name="test_agent", stage="pre", total_tokens=100, api_calls=1)

Env vars (any ONE of these must be set):
    MONITOR_URL       base URL (e.g. http://agent.eba-xxx.us-east-1.elasticbeanstalk.com)
    MONITOR_API_URL   full URL   (e.g. http://.../monitor/status)  -- alternative
    BEANSTALK_URL     base URL   -- alternative

    MONITOR_TOKEN     optional auth header (X-Monitor-Token)
    TARGET_CLOUD      cloud label (default: "aws")
"""
from __future__ import annotations
import os
import sys
import requests

def _resolve_url() -> str:
    full = os.environ.get("MONITOR_API_URL", "").strip().rstrip("/")
    if full:
        return full if full.endswith("/monitor/status") \
                     else f"{full}/monitor/status"
    base = (os.environ.get("MONITOR_URL", "").strip()
            or os.environ.get("BEANSTALK_URL", "").strip()).rstrip("/")
    return f"{base}/monitor/status" if base else ""

def report(
    *,
    agent_name: str,
    stage: str,
    state: str = "passed",
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
    api_key_count: int = 1,
    cloud: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    error: str = "",
    # ── legacy kwargs, swallowed silently ─────────────────────
    requests_count: int | None = None,
    fail_hard: bool = False,
    **_ignored,
) -> bool:
    url = _resolve_url()
    if not url:
        print(
            f"[monitor] no URL env var set (MONITOR_API_URL / MONITOR_URL) — "
            f"skipping report for agent={agent_name}",
            file=sys.stderr, flush=True,
        )
        return False

    if requests_count is not None and api_calls in (None, 0, 1):
        api_calls = int(requests_count)
    if total_tokens is None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)

    payload = {
        "agent_name":                agent_name,
        "stage":                     stage,
        "cloud":                     cloud or os.environ.get("TARGET_CLOUD", "aws"),
        "state":                     state,
        "status":                    status,
        "prompt_tokens":             max(0, int(prompt_tokens     or 0)),
        "completion_tokens":         max(0, int(completion_tokens or 0)),
        "total_tokens":              max(0, int(total_tokens      or 0)),
        "api_calls":                 max(0, int(api_calls         or 0)),
        "requests":                  max(0, int(api_calls         or 0)),
        "task_count":                max(0, int(task_count        or 0)),
        "execution_time_seconds":    max(0.0, float(execution_time_seconds    or 0)),
        "api_response_time_seconds": max(0.0, float(api_response_time_seconds or 0)),
        "api_key_count":             max(0, int(api_key_count or 0)),
    }
    if decision:    payload["decision"]    = str(decision)
    if task_result: payload["task_result"] = str(task_result)
    if provider:    payload["provider"]    = str(provider)
    if model:       payload["model"]       = str(model)
    if error:       payload["error"]       = str(error)[:500]

    headers = {"Content-Type": "application/json"}
    token = os.environ.get("MONITOR_TOKEN", "").strip()
    if token:
        headers["X-Monitor-Token"] = token

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        body = (r.text or "")[:200]
        print(
            f"[monitor] POST {url} agent={agent_name} stage={stage} "
            f"→ {r.status_code}: {body}",
            file=sys.stderr, flush=True,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        print(
            f"[monitor] POST failed for agent={agent_name}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr, flush=True,
        )
        return False

# ── Back-compat alias so existing code using send_agent_status() still works ──
def send_agent_status(**kwargs) -> bool:
    """Alias for report(). Maps old `requests_count` → `api_calls`."""
    if "requests_count" in kwargs and "api_calls" not in kwargs:
        kwargs["api_calls"] = kwargs.pop("requests_count")
    else:
        kwargs.pop("requests_count", None)
    return report(**kwargs)