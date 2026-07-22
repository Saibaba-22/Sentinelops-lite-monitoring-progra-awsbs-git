import os
import time
import requests


def send_agent_status(
    *,
    agent_name,
    stage,
    status,
    decision="none",
    provider="gemini",
    model="gemini-3.1-flash-lite",
    prompt_tokens=0,
    completion_tokens=0,
    total_tokens=0,
    requests_count=0,
    api_key_count=1,
    execution_time_seconds=0.0,
    api_response_time_seconds=0.0,
    error=None,
):
    """
    Send one AI-agent monitoring event to the deployed Flask application.

    Monitoring must never make a CI pipeline fail, so failures are logged only.
    """

    monitor_url = os.getenv("MONITOR_API_URL", "").rstrip("/")
    if not monitor_url:
        print("[monitoring] MONITOR_API_URL not set; AI metrics were not sent.")
        return False

    if not monitor_url.endswith("/monitor/status"):
        monitor_url += "/monitor/status"

    payload = {
        "agent_name": agent_name,
        "stage": stage,
        "cloud": os.getenv("TARGET_CLOUD", "unknown"),
        "status": status,
        "decision": decision,
        "provider": provider,
        "model": model,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "requests": int(requests_count or 0),
        "api_key_count": int(api_key_count or 0),
        "execution_time_seconds": round(float(execution_time_seconds or 0), 4),
        "api_response_time_seconds": round(float(api_response_time_seconds or 0), 4),
        # Keep error out of Prometheus labels. It can be saved in JSON/logs only.
        "error": str(error or "")[:1000],
        "sent_at_epoch": time.time(),
    }

    headers = {"Content-Type": "application/json"}

    monitor_token = os.getenv("MONITOR_TOKEN")
    if monitor_token:
        headers["X-Monitor-Token"] = monitor_token

    try:
        response = requests.post(
            monitor_url,
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        print(f"[monitoring] reported {agent_name}: {status}")
        return True
    except Exception as exc:
        print(f"[monitoring] metric send failed: {exc}")
        return False