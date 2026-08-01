"""JSON status snapshots used by the dashboard and API."""

from __future__ import annotations

import socket
import time
from datetime import datetime, timezone

import psutil

from monitoring import agent_state as agent_state_store
from monitoring.metrics import (
    APP_STATS,
    BUILD_NUMBER,
    DEPLOYMENT_VERSION,
    ENVIRONMENT,
    START_TIME,
)


def system_snapshot() -> dict:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    try:
        load1, load5, load15 = psutil.getloadavg()
        load = {"1m": load1, "5m": load5, "15m": load15}
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
        "hostname": socket.gethostname(),
    }


def application_snapshot() -> dict:
    total = APP_STATS["total_requests"]
    failed = APP_STATS["failed_requests"]
    return {
        "status": "running",
        "health": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "total_requests": total,
        "success_requests": APP_STATS["success_requests"],
        "failed_requests": failed,
        "error_rate": round(failed / total, 4) if total else 0.0,
        "active_sessions": APP_STATS["active_sessions"],
        "active_users": APP_STATS["active_users"],
        "avg_response_time_seconds": round(
            APP_STATS["total_request_time"] / total, 4
        )
        if total
        else 0.0,
        "exceptions": APP_STATS["exceptions"],
        "restart_count": APP_STATS.get("restart_count", 0),
    }


def agent_snapshot() -> dict:
    return agent_state_store.load().get("agents", {})


def deployment_snapshot() -> dict:
    return {
        "version": DEPLOYMENT_VERSION,
        "build_number": BUILD_NUMBER,
        "environment": ENVIRONMENT,
        "uptime_seconds": int(time.time() - START_TIME),
        "container_status": 1,
    }


def build_status() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "application": application_snapshot(),
        "system": system_snapshot(),
        "agent": agent_snapshot(),
        "deployment": deployment_snapshot(),
    }
