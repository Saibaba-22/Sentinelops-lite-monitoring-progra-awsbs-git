"""
Live status collectors.

Builds the JSON snapshot served by ``/api/status`` (and used by the HTML
dashboard). Combines a fresh psutil reading with the mirrored ``APP_STATS``
counters and the persisted AI-agent state.
"""
import time
from datetime import datetime, timezone

import psutil

from monitoring.metrics import (
    APP_STATS,
    START_TIME,
    DEPLOYMENT_VERSION,
    BUILD_NUMBER,
    ENVIRONMENT,
)
from monitoring import agent_state as agent_state_store


def _system_snapshot():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    load = {}
    try:
        l1, l5, l15 = psutil.getloadavg()
        load = {"1m": l1, "5m": l5, "15m": l15}
    except Exception:
        load = {"1m": 0, "5m": 0, "15m": 0}

    boot = psutil.boot_time()
    try:
        logged_in = len(psutil.users())
    except Exception:
        logged_in = 0

    return {
        "cpu_usage_percent": psutil.cpu_percent(interval=None),
        "memory_usage_percent": mem.percent,
        "memory_used_bytes": mem.used,
        "memory_total_bytes": mem.total,
        "disk_usage_percent": disk.percent,
        "disk_total_bytes": disk.total,
        "network_recv_bytes": net.bytes_recv,
        "network_sent_bytes": net.bytes_sent,
        "load_average": load,
        "uptime_seconds": int(time.time() - boot),
        "boot_time": datetime.fromtimestamp(boot, tz=timezone.utc).isoformat(),
        "process_count": len(psutil.pids()),
        "logged_in_users": logged_in,
        "hostname": psutil.users() and __import__("socket").gethostname() or "",
    }


def _application_snapshot():
    total = APP_STATS["total_requests"]
    failed = APP_STATS["failed_requests"]
    error_rate = (failed / total) if total else 0.0
    avg_rt = (APP_STATS["total_request_time"] / total) if total else 0.0
    return {
        "status": "running",
        "health": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "total_requests": total,
        "success_requests": APP_STATS["success_requests"],
        "failed_requests": failed,
        "error_rate": round(error_rate, 4),
        "active_sessions": APP_STATS["active_sessions"],
        "active_users": APP_STATS["active_users"],
        "avg_response_time_seconds": round(avg_rt, 4),
        "exceptions": APP_STATS["exceptions"],
        "restart_count": APP_STATS.get("restart_count", 0),
    }


def _agent_snapshot():
    state = agent_state_store.load()
    return {
        "status": state.get("status", "Idle"),
        "model": state.get("model"),
        "tokens": state.get("tokens", 0),
        "requests": state.get("requests", 0),
        "api_keys": state.get("api_keys", 0),
        "last_run": state.get("last_run"),
        "current_task": state.get("current_task"),
        "last_task": state.get("last_task"),
        "queue_size": state.get("queue_size", 0),
        "accuracy": state.get("accuracy"),
    }


def _deployment_snapshot():
    return {
        "version": DEPLOYMENT_VERSION,
        "build_number": BUILD_NUMBER,
        "environment": ENVIRONMENT,
        "uptime_seconds": int(time.time() - START_TIME),
        "container_status": 1,
    }


def build_status():
    """Return the full aggregated status snapshot as a dict."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "application": _application_snapshot(),
        "system": _system_snapshot(),
        "agent": _agent_snapshot(),
        "deployment": _deployment_snapshot(),
    }
