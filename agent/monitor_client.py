"""Send real CI-agent measurements to the deployed monitor endpoint."""

from __future__ import annotations

import os
import sys

import requests


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
