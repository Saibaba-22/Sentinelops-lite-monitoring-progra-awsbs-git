"""Prometheus metrics and lightweight system collectors."""

from __future__ import annotations

import os
import platform
import socket
import threading
import time
from typing import Any

import psutil
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)

DEPLOYMENT_VERSION = os.getenv("APP_VERSION", "1.0.0")
BUILD_NUMBER = os.getenv("BUILD_NUMBER", "local")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
START_TIME = time.time()

APP_STATS: dict[str, Any] = {
    "total_requests": 0,
    "success_requests": 0,
    "failed_requests": 0,
    "active_sessions": 0,
    "active_users": 0,
    "exceptions": 0,
    "total_request_time": 0.0,
    "restart_count": 0,
}

# Application metrics
app_requests_total = Counter(
    "app_requests_total", "Total HTTP requests.", ["method", "endpoint", "status"]
)
app_request_duration_seconds = Histogram(
    "app_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
app_errors_total = Counter("app_errors_total", "Total HTTP 5xx responses.")
app_exceptions_total = Counter("app_exceptions_total", "Total uncaught exceptions.")
http_status_codes_total = Counter(
    "http_status_codes_total", "HTTP responses by status code.", ["code"]
)
app_active_sessions = Gauge("app_active_sessions", "Active sessions.")
app_active_users = Gauge("app_active_users", "Active users.")
app_uptime_seconds = Gauge("app_uptime_seconds", "Application uptime in seconds.")
app_restart_total = Counter("app_restart_total", "Application process starts.")
python_process_resident_memory_bytes = Gauge(
    "python_process_resident_memory_bytes", "Python process resident memory in bytes."
)
python_process_cpu_percent = Gauge("python_process_cpu_percent", "Python process CPU percent.")
python_thread_count = Gauge("python_thread_count", "Number of Python threads.")

# System metrics
system_cpu_usage_percent = Gauge("system_cpu_usage_percent", "System CPU usage percent.")
system_memory_usage_percent = Gauge("system_memory_usage_percent", "System memory usage percent.")
system_memory_used_bytes = Gauge("system_memory_used_bytes", "System memory used in bytes.")
system_memory_total_bytes = Gauge("system_memory_total_bytes", "System memory total in bytes.")
system_disk_usage_percent = Gauge("system_disk_usage_percent", "Root filesystem usage percent.")
system_disk_read_bytes_total = Gauge("system_disk_read_bytes_total", "Disk bytes read.")
system_disk_write_bytes_total = Gauge("system_disk_write_bytes_total", "Disk bytes written.")
system_network_recv_bytes_total = Gauge("system_network_recv_bytes_total", "Network bytes received.")
system_network_sent_bytes_total = Gauge("system_network_sent_bytes_total", "Network bytes sent.")
system_load_average = Gauge("system_load_average", "System load average.", ["mode"])
system_uptime_seconds = Gauge("system_uptime_seconds", "System uptime in seconds.")
system_boot_time_seconds = Gauge("system_boot_time_seconds", "System boot time.")
system_process_count = Gauge("system_process_count", "Number of processes.")
system_open_file_descriptors = Gauge(
    "system_open_file_descriptors", "Open file descriptors for the app process."
)
system_logged_in_users = Gauge("system_logged_in_users", "Logged-in users.")
system_info = Info("system", "System identity metadata.")
deployment_info = Info("deployment", "Deployment metadata.")

# Agent metrics
AGENT_STATES = ("idle", "running", "approved", "rejected", "failed", "healthy")
AGENT_DECISIONS = ("none", "approved", "rejected", "failed", "healthy", "pass", "fail")
AGENT_LABELS = ["agent_name", "stage", "cloud"]

agent_state = Gauge(
    "agent_state", "Current state of an AI agent.", AGENT_LABELS + ["state"]
)
agent_last_decision = Gauge(
    "agent_last_decision", "Latest decision of an AI agent.", AGENT_LABELS + ["decision"]
)
agent_model_info = Info("agent_model", "AI provider/model metadata.", AGENT_LABELS)
agent_prompt_tokens_total = Counter(
    "agent_prompt_tokens_total", "Prompt tokens used.", AGENT_LABELS + ["provider", "model"]
)
agent_completion_tokens_total = Counter(
    "agent_completion_tokens_total",
    "Completion tokens used.",
    AGENT_LABELS + ["provider", "model"],
)
agent_token_usage_total = Counter(
    "agent_token_usage_total", "Total tokens used.", AGENT_LABELS + ["provider", "model"]
)
agent_api_calls_total = Counter(
    "agent_api_calls_total",
    "AI provider calls.",
    AGENT_LABELS + ["provider", "model", "status"],
)
agent_tasks_total = Counter(
    "agent_tasks_total", "Agent executions by result.", AGENT_LABELS + ["result"]
)
agent_api_key_count = Gauge(
    "agent_api_key_count", "Number of configured API keys.", AGENT_LABELS + ["provider"]
)
agent_last_run_timestamp_seconds = Gauge(
    "agent_last_run_timestamp_seconds", "Last agent report timestamp.", AGENT_LABELS
)
agent_execution_time_seconds = Gauge(
    "agent_execution_time_seconds", "Latest agent execution duration.", AGENT_LABELS
)
agent_execution_duration_seconds = Histogram(
    "agent_execution_duration_seconds",
    "Agent execution duration distribution.",
    AGENT_LABELS,
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300),
)
agent_api_response_time_seconds = Histogram(
    "agent_api_response_time_seconds",
    "AI provider response latency.",
    AGENT_LABELS + ["provider", "model"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
)

# Deployment metrics
deployment_uptime_seconds = Gauge("deployment_uptime_seconds", "Deployment uptime.")
deployment_restart_total = Counter("deployment_restart_total", "Deployment starts.")
container_status = Gauge("container_status", "1 when the app process is healthy.")


def _open_fds(proc: psutil.Process) -> int:
    try:
        return proc.num_fds()
    except Exception:
        return 0


def update_metrics() -> None:
    """Refresh process and host metrics without allowing one collector to fail all others."""
    try:
        proc = psutil.Process()
        python_process_resident_memory_bytes.set(proc.memory_info().rss)
        python_process_cpu_percent.set(proc.cpu_percent(interval=None))
        python_thread_count.set(proc.num_threads())
        system_open_file_descriptors.set(_open_fds(proc))
    except Exception:
        pass

    try:
        system_cpu_usage_percent.set(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        system_memory_usage_percent.set(mem.percent)
        system_memory_used_bytes.set(mem.used)
        system_memory_total_bytes.set(mem.total)
        disk = psutil.disk_usage("/")
        system_disk_usage_percent.set(disk.percent)
        net = psutil.net_io_counters()
        system_network_recv_bytes_total.set(net.bytes_recv)
        system_network_sent_bytes_total.set(net.bytes_sent)
        io = psutil.disk_io_counters()
        if io:
            system_disk_read_bytes_total.set(io.read_bytes)
            system_disk_write_bytes_total.set(io.write_bytes)
    except Exception:
        pass

    try:
        load1, load5, load15 = psutil.getloadavg()
        for mode, value in (("1m", load1), ("5m", load5), ("15m", load15)):
            system_load_average.labels(mode=mode).set(value)
    except Exception:
        pass

    try:
        boot = psutil.boot_time()
        system_boot_time_seconds.set(boot)
        system_uptime_seconds.set(time.time() - boot)
        system_process_count.set(len(psutil.pids()))
        system_logged_in_users.set(len(psutil.users()))
    except Exception:
        pass

    app_uptime_seconds.set(time.time() - START_TIME)
    deployment_uptime_seconds.set(time.time() - START_TIME)
    container_status.set(1)


def _metrics_loop(interval: int) -> None:
    while True:
        try:
            update_metrics()
        except Exception:
            pass
        time.sleep(max(1, interval))


def start_metrics_updater(interval: int = 5) -> None:
    thread = threading.Thread(target=_metrics_loop, args=(interval,), daemon=True)
    thread.start()

def public_ip() -> str:
    """Return a public IP only when explicitly enabled; startup never depends on a network call."""
    if os.getenv("COLLECT_PUBLIC_IP", "0") != "1":
        return "unknown"
    try:
        import urllib.request

        with urllib.request.urlopen("https://api.ipify.org", timeout=2) as response:
            return response.read().decode().strip() or "unknown"
    except Exception:
        return "unknown"


def private_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _init() -> None:
    system_info.info(
        {
            "hostname": socket.gethostname(),
            "public_ip": public_ip(),
            "private_ip": private_ip(),
            "os": platform.system(),
            "python_version": platform.python_version(),
        }
    )
    deployment_info.info(
        {"version": DEPLOYMENT_VERSION, "build": BUILD_NUMBER, "environment": ENVIRONMENT}
    )
    app_restart_total.inc()
    deployment_restart_total.inc()
    APP_STATS["restart_count"] = int(app_restart_total._value.get())
    update_metrics()


_init()
