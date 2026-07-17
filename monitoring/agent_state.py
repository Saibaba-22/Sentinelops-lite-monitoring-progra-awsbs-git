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
    "status": "Idle",
    "tokens": 0,
    "requests": 0,
    "api_keys": 0,
    "model": "gemini-2.5-flash",
    "last_run": None,
    "api_key_name": "GEMINI_API_KEY",
    "current_task": None,
    "last_task": None,
    "queue_size": 0,
    "accuracy": None,
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
