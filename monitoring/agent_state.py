"""Small atomic JSON store for the latest CI-agent status."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS_FILE = os.path.join(BASE_DIR, "logs", "agent_stats.json")
_LOCK = threading.Lock()

DEFAULT_STATE = {
    "status": "idle",
    "decision": "none",
    "agents": {
        name: {
            "agent_name": name,
            "status": "idle",
            "decision": "none",
            "stage": "unknown",
            "cloud": "unknown",
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
            "api_key_count": 0,
            "last_run": None,
            "execution_time_seconds": 0,
        }
        for name in ("test_agent", "errors_agent", "final_agent")
    },
}


def load() -> dict:
    try:
        with open(STATS_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        state = copy.deepcopy(DEFAULT_STATE)
        state.update({k: v for k, v in data.items() if k != "agents"})
        state["agents"].update(data.get("agents", {}))
        return state
    except (OSError, ValueError, TypeError):
        return copy.deepcopy(DEFAULT_STATE)


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    with _LOCK:
        fd, temporary = tempfile.mkstemp(
            prefix="agent_stats.", suffix=".tmp", dir=os.path.dirname(STATS_FILE)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            os.replace(temporary, STATS_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
