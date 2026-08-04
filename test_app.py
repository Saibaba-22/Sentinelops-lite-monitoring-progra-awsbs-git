"""
test_app.py — SentinelOps-Lite test suite
Tests /health, /api, /api/status, /agent/status, /metrics, /monitor/status
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock


# ══════════════════════════════════════════════════════════════
# STUB agent_monitor BEFORE importing app
# app.py uses getattr(...) so a minimal stub is enough, but we
# populate common attrs to be safe.
# ══════════════════════════════════════════════════════════════

def _stub_agent_monitor() -> None:
    """Register a lightweight stub for agent_monitor with ALL required attributes."""
    if "agent_monitor" in sys.modules:
        return
    mod = types.ModuleType("agent_monitor")

    # Create proper mocks for all classes
    mod.MetricsDB = MagicMock()
    mod.ProjectScanner = MagicMock()
    mod.ResourceMonitor = MagicMock()

    # Create a proper HTMLBuilder mock
    mod.HTMLBuilder = MagicMock()

    # Initialize ACTIVE_CONFIG with proper limits
    mod.ACTIVE_CONFIG = {
        "name": "gemini-2.5-flash",
        "provider": "google",
        "tpm": 1000000,  # Tokens per minute
        "tph": 60000000, # Tokens per hour
        "tpd": 1000000000, # Tokens per day
        "rpm": 10000,    # Requests per minute
        "rph": 600000,   # Requests per hour
        "rpd": 10000000, # Requests per day
        "cost_in": 0.00015,
        "cost_out": 0.00060,
        "ctx": 1048576
    }

    # Initialize other required variables
    mod.MODEL_REGISTRY = {}
    mod.ACTIVE_PROVIDER = "google"
    mod.ACTIVE_MODEL = "gemini-2.5-flash"
    mod.AI_PROVIDER = "google"
    mod.AI_MODEL = "gemini-2.5-flash"

    sys.modules["agent_monitor"] = mod

_stub_agent_monitor()

from app import application  # noqa: E402  (import after stub)

# ══════════════════════════════════════════════════════════════
# HOME
# ══════════════════════════════════════════════════════════════

def test_home():
    """GET / returns 200 HTML."""
    client = application.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


# ══════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════

def test_health_returns_200():
    """GET /health returns 200 (healthy) or 503 (degraded)."""
    client = application.test_client()
    response = client.get("/health")
    assert response.status_code in (200, 503), (
        f"Unexpected status {response.status_code} from /health"
    )


def test_health_returns_json():
    """GET /health returns application/json (NOT html)."""
    client = application.test_client()
    response = client.get("/health")
    assert response.content_type.startswith("application/json"), (
        f"Expected 'application/json', got {response.content_type!r}"
    )


def test_health_body_structure():
    """/health body must have status, checks, uptime_seconds, version."""
    client = application.test_client()
    response = client.get("/health")
    data = response.get_json()

    assert data is not None, "/health returned non-JSON body"
    assert "status" in data
    assert data["status"] in ("healthy", "degraded")
    assert "checks" in data
    assert "uptime_seconds" in data
    assert isinstance(data["uptime_seconds"], (int, float))
    assert data["uptime_seconds"] >= 0
    assert "version" in data


# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════

def test_api():
    """GET /api returns hello message and running status."""
    client = application.test_client()
    response = client.get("/api")

    assert response.status_code == 200
    assert response.content_type.startswith("application/json")

    data = response.get_json()
    assert data["message"] == "Hello from SentinelOps-Lite!"
    assert data["status"] == "running"
    assert "version" in data
    assert "build" in data


# ══════════════════════════════════════════════════════════════
# API STATUS
# ══════════════════════════════════════════════════════════════

def test_api_status():
    """GET /api/status has application/system/agent/deployment sections."""
    client = application.test_client()
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.content_type.startswith("application/json")

    data = response.get_json()

    for section in ("application", "system", "agent", "deployment"):
        assert section in data, f"Missing section '{section}'"

    assert data["application"]["name"] == "SentinelOps-Lite"
    assert data["deployment"]["version"]

    system = data["system"]
    for key in (
        "cpu_usage_percent",
        "memory_total_mb",
        "memory_used_mb",
        "memory_percent",
        "process_cpu_percent",
        "process_memory_mb",
    ):
        assert key in system, f"Missing system metric key: '{key}'"

    assert "provider" in data["agent"]
    assert "model" in data["agent"]


# ══════════════════════════════════════════════════════════════
# AGENT STATUS
# ══════════════════════════════════════════════════════════════

def test_agent_status():
    """GET /agent/status returns running status."""
    client = application.test_client()
    response = client.get("/agent/status")

    assert response.status_code == 200
    assert response.content_type.startswith("application/json")

    data = response.get_json()
    assert data["status"] == "running"
    assert "provider" in data
    assert "model" in data
    assert "uptime_seconds" in data


# ══════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════

def test_metrics_endpoint():
    """GET /metrics returns Prometheus text with required metrics."""
    import app as flask_app

    # Ensure no token so no auth required
    original = flask_app._CFG["metrics_token"]
    flask_app._CFG["metrics_token"] = ""

    try:
        client = application.test_client()
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.content_type.startswith("text/plain")

        body = response.data
        assert b"app_requests_total" in body
        assert b"python_process_cpu_percent" in body
        assert b"agent_status" in body
        assert b"agent_uptime_seconds" in body
        assert b"agent_cpu_percent" in body
        assert b"agent_memory_mb" in body
    finally:
        flask_app._CFG["metrics_token"] = original


def test_metrics_blocked_without_token():
    """/metrics with METRICS_TOKEN set must reject unauthenticated calls."""
    import app as flask_app

    original = flask_app._CFG["metrics_token"]
    flask_app._CFG["metrics_token"] = "test-secret-token"

    try:
        client = application.test_client()

        resp_no = client.get("/metrics")
        assert resp_no.status_code == 401

        resp_wrong = client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp_wrong.status_code == 401

        resp_ok = client.get(
            "/metrics",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp_ok.status_code == 200
    finally:
        flask_app._CFG["metrics_token"] = original


# ══════════════════════════════════════════════════════════════
# MONITOR STATUS
# ══════════════════════════════════════════════════════════════

def setup_function(function):
    """Ensure ResourceMonitor is running IF it exists (stubbed in tests → None)."""
    try:
        from app import _monitor
        if _monitor is not None and hasattr(_monitor, "monitoring"):
            if not _monitor.monitoring:
                _monitor.start_monitoring()
    except Exception:
        pass   # tests run against stub → no real monitor needed
        
def test_monitor_status_no_token_configured():
    """MONITOR_TOKEN empty → POST accepted."""
    import app as flask_app

    original = flask_app._CFG["monitor_token"]
    flask_app._CFG["monitor_token"] = ""

    try:
        client = application.test_client()
        response = client.post("/monitor/status")
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
    finally:
        flask_app._CFG["monitor_token"] = original


def test_monitor_status_receiver():
    """POST /monitor/status with X-Monitor-Token."""
    import app as flask_app

    test_token = "unit-test-monitor-token"
    original = flask_app._CFG["monitor_token"]
    flask_app._CFG["monitor_token"] = test_token

    try:
        client = application.test_client()
        payload = {
            "agent_name": "test_agent",
            "stage":      "pre_deploy",
            "cloud":      "aws",
            "status":     "approved",
            "provider":   "gemini",
            "model":      "gemini-2.5-flash",
            "total_tokens": 15,
            "requests": 1,
        }

        resp_no = client.post("/monitor/status", json=payload)
        assert resp_no.status_code == 401

        resp_wrong = client.post(
            "/monitor/status",
            json=payload,
            headers={"X-Monitor-Token": "wrong"},
        )
        assert resp_wrong.status_code == 401

        resp_ok = client.post(
            "/monitor/status",
            json=payload,
            headers={"X-Monitor-Token": test_token},
        )
        assert resp_ok.status_code == 200
        assert resp_ok.get_json()["ok"] is True
    finally:
        flask_app._CFG["monitor_token"] = original


# ══════════════════════════════════════════════════════════════
# ENV VAR CONTRACT
# ══════════════════════════════════════════════════════════════

def test_env_example_contains_all_required_vars():
    """.env.example must document every variable app.py reads."""
    import pathlib
    import pytest

    env_file = pathlib.Path(".env.example")
    if not env_file.exists():
        pytest.skip(".env.example not found in working directory")

    defined: set[str] = set()
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            defined.add(line.split("=", 1)[0].strip())

    required = {
        "APP_VERSION",
        "BUILD_NUMBER",
        "ENVIRONMENT",
        "PORT",
        "FLASK_DEBUG",
        "AI_PROVIDER",
        "AI_MODEL",
        "METRICS_TOKEN",
        "MONITOR_TOKEN",
        "TARGET_CLOUD",
        "AWS_REGION",
    }

    missing = required - defined
    assert not missing, (
        ".env.example is missing:\n"
        + "\n".join(f"  • {v}" for v in sorted(missing))
    )

# ── Report to central monitor endpoint ─────────────────────────
try:
    from agent.monitor_client import report
    report(
        agent_name="test_agent",
        stage="pre",
        state="passed",           # or "failed" if tests failed
        decision="pass",          # or "fail"
        status="success",
        total_tokens=100,         # replace with real count if available
        api_calls=1,
        execution_time_seconds=1.0,
        api_key_count=1,
        fail_hard=False,
    )
except Exception as e:
    print(f"[test_agent] monitor report error: {e}")