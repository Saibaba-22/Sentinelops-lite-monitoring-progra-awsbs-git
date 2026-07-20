"""
AI Agent state store.

Persists the latest agent status broadcast by ``agent.py`` (the CI release-gate)
via the ``/monitor/status`` endpoint into ``logs/agent_stats.json`` so the
dashboard and ``/agent/status`` can render it without depending on Prometheus.
"""
import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS_FILE = os.path.join(BASE_DIR, "logs", "agent_stats.json")
_LOCK = threading.Lock()

DEFAULT_STATE = {
    "agents": {
        "test_agent": {
            "status": "idle",
            "decision": "none",
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
            "api_key_count": 0,
            "last_run": None,
            "execution_time_seconds": 0,
        },
        "errors_agent": {
            "status": "idle",
            "decision": "none",
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
            "api_key_count": 0,
            "last_run": None,
            "execution_time_seconds": 0,
        },
        "final_agent": {
            "status": "idle",
            "decision": "none",
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
            "api_key_count": 0,
            "last_run": None,
            "execution_time_seconds": 0,
        },
    }
}


def load():
    """Return the persisted agent state merged over defaults."""
    try:
        with open(STATS_FILE) as fh:
            data = json.load(fh)
        return {**DEFAULT_STATE, **data}
    except Exception:
        return dict(DEFAULT_STATE)


def save(data):
    """Persist agent state atomically-ish (guarded by a lock)."""
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    with _LOCK:
        with open(STATS_FILE, "w") as fh:
            json.dump(data, fh, indent=2)
