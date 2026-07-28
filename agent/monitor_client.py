"""Best-effort client for posting CI-agent status to Flask."""

from __future__ import annotations

import os

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
    url = os.getenv("MONITOR_API_URL", "").strip()
    if not url:
        return False
    payload = {
        "agent_name": agent_name,
        "stage": stage,
        "cloud": os.getenv("TARGET_CLOUD", os.getenv("ENVIRONMENT", "unknown")),
        "status": status,
        "decision": decision,
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "requests": requests_count,
        "api_key_count": api_key_count,
        "execution_time_seconds": execution_time_seconds,
        "api_response_time_seconds": api_response_time_seconds,
    }
    if error:
        payload["error"] = error[:500]
    headers = {}
    token = os.getenv("MONITOR_TOKEN", "")
    if token:
        headers["X-Monitor-Token"] = token
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False
