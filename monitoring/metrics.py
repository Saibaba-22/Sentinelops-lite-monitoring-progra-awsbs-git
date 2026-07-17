"""
Prometheus metric definitions and background collectors for SentinelOps-Lite.

Every metric the platform exposes on ``/metrics`` is declared here so that:
  * Prometheus can scrape them for Grafana dashboards.
  * A background thread keeps the expensive system/process gauges fresh
    without blocking per-request work.

No secrets are hard-coded; deployment identity is sourced from the
environment (see ``DEPLOYMENT_VERSION`` / ``BUILD_NUMBER`` / ``ENVIRONMENT``).
"""
import os
import time
import socket
import platform
import threading

import psutil
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# ---------------------------------------------------------------------------
# Deployment / environment metadata (env driven, no hardcoded secrets)
# ---------------------------------------------------------------------------
DEPLOYMENT_VERSION = os.getenv("APP_VERSION", "1.0.0")
BUILD_NUMBER = os.getenv("BUILD_NUMBER", "local")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
START_TIME = time.time()

# In-memory convenience counters mirrored into Prometheus metrics. These power
# the lightweight JSON ``/api/status`` endpoint without parsing exposition text.
APP_STATS = {
    "total_requests": 0,
    "success_requests": 0,
    "failed_requests": 0,
    "active_sessions": 0,
    "active_users": 0,
    "exceptions": 0,
    "total_request_time": 0.0,
}

# ---------------------------------------------------------------------------
# Application metrics
# ---------------------------------------------------------------------------
app_requests_total = Counter(
    "app_requests_total",
    "Total HTTP requests handled by the application.",
    ["method", "endpoint", "status"],
)
app_request_duration_seconds = Histogram(
    "app_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
app_errors_total = Counter("app_errors_total", "Total application errors (HTTP 5xx).")
app_exceptions_total = Counter("app_exceptions_total", "Total uncaught exceptions.")
http_status_codes_total = Counter(
    "http_status_codes_total", "Count of HTTP responses by status code.", ["code"]
)
app_active_sessions = Gauge("app_active_sessions", "Number of active sessions.")
app_active_users = Gauge("app_active_users", "Number of active users.")
app_uptime_seconds = Gauge("app_uptime_seconds", "Application uptime in seconds.")
app_restart_total = Counter("app_restart_total", "Monotonic application restart counter.")
python_process_resident_memory_bytes = Gauge(
    "python_process_resident_memory_bytes", "Resident memory of the Python process (bytes)."
)
python_process_cpu_percent = Gauge(
    "python_process_cpu_percent", "CPU usage percent of the Python process."
)
python_thread_count = Gauge("python_thread_count", "Number of Python threads.")

# ---------------------------------------------------------------------------
# System metrics (a curated subset also exposed by node-exporter; kept here so
# the application is self-describing and the HTML dashboard has a single source)
# ---------------------------------------------------------------------------
system_cpu_usage_percent = Gauge("system_cpu_usage_percent", "System CPU usage percent.")
system_memory_usage_percent = Gauge("system_memory_usage_percent", "System memory usage percent.")
system_memory_used_bytes = Gauge("system_memory_used_bytes", "System memory used (bytes).")
system_memory_total_bytes = Gauge("system_memory_total_bytes", "System memory total (bytes).")
system_disk_usage_percent = Gauge("system_disk_usage_percent", "Root filesystem usage percent.")
system_disk_read_bytes_total = Gauge(
    "system_disk_read_bytes_total", "Cumulative disk bytes read."
)
system_disk_write_bytes_total = Gauge(
    "system_disk_write_bytes_total", "Cumulative disk bytes written."
)
system_network_recv_bytes_total = Gauge(
    "system_network_recv_bytes_total", "Cumulative network bytes received."
)
system_network_sent_bytes_total = Gauge(
    "system_network_sent_bytes_total", "Cumulative network bytes sent."
)
system_load_average = Gauge("system_load_average", "System load average.", ["mode"])
system_uptime_seconds = Gauge("system_uptime_seconds", "System uptime in seconds.")
system_boot_time_seconds = Gauge("system_boot_time_seconds", "System boot time (unix epoch).")
system_process_count = Gauge("system_process_count", "Number of running processes.")
system_open_file_descriptors = Gauge(
    "system_open_file_descriptors", "Open file descriptors of the application process."
)
system_logged_in_users = Gauge("system_logged_in_users", "Number of logged-in users.")

# Static identity metadata exposed as Prometheus Info series.
system_info = Info("system", "System identity metadata.")
deployment_info = Info("deployment", "Deployment metadata.")

# ---------------------------------------------------------------------------
# AI Agent metrics
# ---------------------------------------------------------------------------
# Numeric enum mapping for the current agent state gauge.
AGENT_STATES = {
    "idle": 0,
    "running": 1,
    "waiting": 2,
    "approved": 3,
    "rejected": 4,
    "failed": 5,
}
agent_state = Gauge(
    "agent_state", "Current AI agent state as a numeric enum (1 = active).", ["state"]
)
agent_tasks_total = Counter(
    "agent_tasks_total", "AI agent task outcomes.", ["result"]
)
agent_execution_time_seconds = Gauge(
    "agent_execution_time_seconds", "Last agent execution time in seconds."
)
agent_avg_execution_time_seconds = Gauge(
    "agent_avg_execution_time_seconds", "Average agent execution time in seconds."
)
agent_queue_size = Gauge("agent_queue_size", "AI agent task queue size.")
agent_queue_wait_seconds = Gauge("agent_queue_wait_seconds", "AI agent queue wait time (s).")
agent_token_usage_total = Counter("agent_token_usage_total", "Total tokens used by the agent.")
agent_api_calls_total = Counter("agent_api_calls_total", "AI agent API calls.", ["status"])
agent_api_response_time_seconds = Gauge(
    "agent_api_response_time_seconds", "AI agent API response time in seconds."
)
agent_total_decisions = Counter("agent_total_decisions", "Total AI agent decisions.")
agent_accuracy = Gauge("agent_accuracy", "AI agent decision accuracy (0-1).")
agent_current_task = Gauge(
    "agent_current_task", "Current task id (1 if a task is active).", ["task"]
)
agent_last_task = Gauge("agent_last_task", "Last task id (1 if known).", ["task"])

# ---------------------------------------------------------------------------
# Deployment metrics
# ---------------------------------------------------------------------------
deployment_uptime_seconds = Gauge("deployment_uptime_seconds", "Deployment uptime (seconds).")
deployment_restart_total = Counter("deployment_restart_total", "Deployment restart counter.")
container_status = Gauge("container_status", "Container health status (1 = healthy).")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _public_ip():
    """Best-effort public IP lookup; never raises."""
    try:
        import urllib.request

        with urllib.request.urlopen("https://api.ipify.org", timeout=2) as resp:
            return resp.read().decode().strip() or "unknown"
    except Exception:
        return "unknown"


def _private_ip():
    """Best-effort private IP lookup; never raises."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _open_fds(proc):
    try:
        return proc.num_fds()
    except Exception:
        return 0


def _set_agent_state(active_state: str):
    """Set the agent_state gauge so exactly one state holds its enum value."""
    active = str(active_state).lower()
    for name, value in AGENT_STATES.items():
        agent_state.labels(state=name).set(value if name == active else 0)


# ---------------------------------------------------------------------------
# Live metric update (called by the background thread)
# ---------------------------------------------------------------------------
def update_metrics():
    """Refresh system/process gauges from psutil. Safe to call repeatedly."""
    proc = psutil.Process()
    python_process_resident_memory_bytes.set(proc.memory_info().rss)
    python_process_cpu_percent.set(proc.cpu_percent(interval=None))
    python_thread_count.set(proc.num_threads())
    system_open_file_descriptors.set(_open_fds(proc))

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

    try:
        load1, load5, load15 = psutil.getloadavg()
        system_load_average.labels(mode="1m").set(load1)
        system_load_average.labels(mode="5m").set(load5)
        system_load_average.labels(mode="15m").set(load15)
    except Exception:
        pass

    boot = psutil.boot_time()
    system_boot_time_seconds.set(boot)
    system_uptime_seconds.set(time.time() - boot)
    system_process_count.set(len(psutil.pids()))

    try:
        system_logged_in_users.set(len(psutil.users()))
    except Exception:
        pass

    app_uptime_seconds.set(time.time() - START_TIME)
    deployment_uptime_seconds.set(time.time() - START_TIME)
    container_status.set(1)


def _metrics_loop(interval: int = 5):
    while True:
        try:
            update_metrics()
        except Exception:
            # Never let the background thread die.
            pass
        time.sleep(interval)


def start_metrics_updater(interval: int = 5):
    """Spawn the daemon thread that keeps gauges fresh."""
    thread = threading.Thread(target=_metrics_loop, args=(interval,), daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# One-time initialisation (runs at import / process start)
# ---------------------------------------------------------------------------
def _init():
    system_info.info(
        {
            "hostname": socket.gethostname(),
            "public_ip": _public_ip(),
            "private_ip": _private_ip(),
            "os": platform.system(),
            "python_version": platform.python_version(),
        }
    )
    deployment_info.info(
        {
            "version": DEPLOYMENT_VERSION,
            "build": BUILD_NUMBER,
            "environment": ENVIRONMENT,
        }
    )
    _set_agent_state("idle")
    app_restart_total.inc()
    deployment_restart_total.inc()
    APP_STATS["restart_count"] = int(app_restart_total._value.get())
    # Prime an initial reading so scrapes are never empty.
    try:
        update_metrics()
    except Exception:
        pass


_init()
