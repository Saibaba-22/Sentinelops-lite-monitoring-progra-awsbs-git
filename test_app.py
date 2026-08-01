"""
Unit tests for SentinelOps-Lite (app.py)

Run:
    pytest test_app.py -v
    pytest test_app.py -v --tb=short

Every test is self-contained:
  - Uses application.test_client() directly
  - No shared global state between tests
  - No external network calls
  - Deterministic regardless of run order
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock


# ══════════════════════════════════════════════════════════════
# STUB agent_monitor BEFORE importing app
# This prevents ImportError if agent_monitor is not installed.
# ══════════════════════════════════════════════════════════════

def _stub_agent_monitor() -> None:
    """Register a lightweight stub for agent_monitor."""
    if "agent_monitor" in sys.modules:
        return
    mod = types.ModuleType("agent_monitor")
    bp = MagicMock()
    bp.name = "scanner"       # Flask requires blueprint.name to be a string
    mod.scanner_bp = bp
    sys.modules["agent_monitor"] = mod


_stub_agent_monitor()

from app import application  # noqa: E402  (import after stub)


# ══════════════════════════════════════════════════════════════
# HOME
# ══════════════════════════════════════════════════════════════

def test_home():
    """GET / returns 200 HTML (the dashboard page)."""
    client = application.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


# ══════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════

def test_health_returns_200():
    """
    GET /health must return HTTP 200 (or 503 when degraded).
    Both are valid — probes read the body, not just the status code.
    """
    client = application.test_client()
    response = client.get("/health")
    # 200 = healthy, 503 = degraded — both are intentional
    assert response.status_code in (200, 503), (
        f"Unexpected status {response.status_code} from /health"
    )


def test_health_returns_json():
    """
    FIX for the original failing test.

    BEFORE (broken):
        assert response.content_type.startswith("text/html")
        → FAILS because app.py returns jsonify(), not render_template()

    AFTER (correct):
        assert response.content_type.startswith("application/json")
        → PASSES because /health now returns a JSON health payload

    WHY the change was made in app.py:
        Kubernetes liveness probes, load balancers, and monitoring
        tools all expect JSON from /health — not an HTML page.
        render_template("index.html") was wrong for a health endpoint.
    """
    client = application.test_client()
    response = client.get("/health")

    # ✅ Correct assertion — app returns JSON, NOT HTML
    assert response.content_type.startswith("application/json"), (
        f"Expected 'application/json', got {response.content_type!r}.\n"
        "If this fails, check that app.py /health uses jsonify() "
        "and NOT render_template()."
    )


def test_health_body_structure():
    """Response body must contain required fields for probe compatibility."""
    client = application.test_client()
    response = client.get("/health")
    data = response.get_json()

    assert data is not None, \
        "/health returned non-JSON body"

    assert "status" in data, \
        f"Missing 'status' field. Got keys: {list(data.keys())}"

    assert data["status"] in ("healthy", "degraded"), \
        f"'status' must be 'healthy' or 'degraded', got {data['status']!r}"

    assert "checks" in data, \
        "Missing 'checks' field — required for probe detail"

    assert "uptime_seconds" in data, \
        "Missing 'uptime_seconds' field"

    assert isinstance(data["uptime_seconds"], (int, float)), \
        f"'uptime_seconds' must be numeric, got {type(data['uptime_seconds'])}"

    assert data["uptime_seconds"] >= 0, \
        f"'uptime_seconds' cannot be negative, got {data['uptime_seconds']}"

    assert "version" in data, \
        "Missing 'version' field"


# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════

def test_api():
    """GET /api returns the hello message and running status."""
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
    """GET /api/status returns all four top-level sections."""
    client = application.test_client()
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.content_type.startswith("application/json")

    data = response.get_json()

    # All four sections must be present
    for section in ("application", "system", "agent", "deployment"):
        assert section in data, \
            f"Missing section '{section}' in /api/status response"

    # Application block
    assert data["application"]["name"] == "SentinelOps-Lite"
    assert data["deployment"]["version"]

    # System block — all metric keys must be present
    system = data["system"]
    for key in (
        "cpu_usage_percent",
        "memory_total_mb",
        "memory_used_mb",
        "memory_percent",
        "process_cpu_percent",
        "process_memory_mb",
    ):
        assert key in system, \
            f"Missing system metric key: '{key}'"

    # Agent block
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
    assert "status" in data
    assert data["status"] == "running"
    assert "provider" in data
    assert "model" in data
    assert "uptime_seconds" in data


# ══════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════

def test_metrics_endpoint():
    """
    GET /metrics returns Prometheus text format with required metric names.
    METRICS_TOKEN is empty (default) so no auth header is needed.
    """
    client = application.test_client()
    response = client.get("/metrics")

    assert response.status_code == 200, (
        f"Got {response.status_code} — if METRICS_TOKEN is set in your "
        "environment, /metrics requires Authorization: Bearer <token>"
    )
    assert response.content_type.startswith("text/plain")

    body = response.data

    # Original metrics — must still be present for backward compatibility
    assert b"app_requests_total" in body, \
        "Missing metric: app_requests_total"
    assert b"python_process_cpu_percent" in body, \
        "Missing metric: python_process_cpu_percent"

    # New agent metrics — added in the app.py update
    assert b"agent_status" in body, \
        "Missing metric: agent_status"
    assert b"agent_uptime_seconds" in body, \
        "Missing metric: agent_uptime_seconds"
    assert b"agent_cpu_percent" in body, \
        "Missing metric: agent_cpu_percent"
    assert b"agent_memory_mb" in body, \
        "Missing metric: agent_memory_mb"


def test_metrics_blocked_without_token():
    """
    When METRICS_TOKEN is configured, unauthenticated requests
    must receive HTTP 401 — not 200.

    FIX: We patch _CFG directly (not os.environ) because app.py
    reads os.environ once at import time into _CFG.
    monkeypatch.setenv() after import has no effect on _CFG.
    """
    import app as flask_app

    # Save and patch _CFG directly
    original_token = flask_app._CFG["metrics_token"]
    flask_app._CFG["metrics_token"] = "test-secret-token"

    try:
        client = application.test_client()

        # No token → 401
        resp_no_token = client.get("/metrics")
        assert resp_no_token.status_code == 401, (
            f"Expected 401 without token, got {resp_no_token.status_code}"
        )

        # Wrong token → 401
        resp_wrong = client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp_wrong.status_code == 401, (
            f"Expected 401 with wrong token, got {resp_wrong.status_code}"
        )

        # Correct token → 200
        resp_ok = client.get(
            "/metrics",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert resp_ok.status_code == 200, (
            f"Expected 200 with correct token, got {resp_ok.status_code}"
        )

    finally:
        # Always restore original value — never leave patched state
        flask_app._CFG["metrics_token"] = original_token


# ══════════════════════════════════════════════════════════════
# MONITOR STATUS
# ══════════════════════════════════════════════════════════════

def test_monitor_status_no_token_configured():
    """
    When MONITOR_TOKEN is empty (default), any POST is accepted.
    """
    import app as flask_app

    original = flask_app._CFG["monitor_token"]
    flask_app._CFG["monitor_token"] = ""   # ensure open auth

    try:
        client = application.test_client()
        response = client.post("/monitor/status")
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
    finally:
        flask_app._CFG["monitor_token"] = original


def test_monitor_status_receiver():
    """
    Verify that an authorized CI-agent monitoring event is accepted.

    FIX vs original test:
        Original used monkeypatch.setenv("MONITOR_TOKEN", ...) which
        has NO effect because app.py reads os.environ once at import
        time into _CFG["monitor_token"].

        Correct approach: patch _CFG["monitor_token"] directly,
        then restore it in a finally block.

    The extra payload fields (provider, model, tokens, etc.) are
    accepted by the endpoint but not validated — only the token
    matters for the 200 OK response.
    """
    import app as flask_app

    test_token = "unit-test-monitor-token"

    # Patch _CFG directly — this is what app.py actually reads
    original = flask_app._CFG["monitor_token"]
    flask_app._CFG["monitor_token"] = test_token

    try:
        client = application.test_client()

        payload = {
            "agent_name":                "test_agent",
            "stage":                     "pre_deploy",
            "cloud":                     "aws",
            "status":                    "approved",
            "decision":                  "pass",
            "provider":                  "gemini",
            "model":                     "gemini-2.5-flash",
            "prompt_tokens":             10,
            "completion_tokens":         5,
            "total_tokens":              15,
            "requests":                  1,
            "api_key_count":             1,
            "execution_time_seconds":    1.0,
            "api_response_time_seconds": 0.5,
        }

        # ── Without token → must be rejected ─────────────────
        resp_no_token = client.post("/monitor/status", json=payload)
        assert resp_no_token.status_code == 401, (
            f"Expected 401 without token, got {resp_no_token.status_code}"
        )

        # ── With wrong token → must be rejected ───────────────
        resp_wrong = client.post(
            "/monitor/status",
            json=payload,
            headers={"X-Monitor-Token": "completely-wrong"},
        )
        assert resp_wrong.status_code == 401, (
            f"Expected 401 with wrong token, got {resp_wrong.status_code}"
        )

        # ── With correct token → must be accepted ─────────────
        resp_ok = client.post(
            "/monitor/status",
            json=payload,
            headers={"X-Monitor-Token": test_token},
        )
        assert resp_ok.status_code == 200, (
            f"Expected 200 with correct token, got {resp_ok.status_code}"
        )
        body = resp_ok.get_json()
        assert body is not None,    "Response body is not JSON"
        assert body["ok"] is True,  f"Expected ok=True, got {body}"

    finally:
        # Always restore — never leave patched global state
        flask_app._CFG["monitor_token"] = original


# ══════════════════════════════════════════════════════════════
# ENV VAR CONTRACT  — .env.example completeness check
# ══════════════════════════════════════════════════════════════

def test_env_example_contains_all_required_vars():
    """
    Verify .env.example documents every variable app.py reads.
    This test catches the METRICS_TOKEN omission that blocked CI.
    """
    import pathlib

    env_file = pathlib.Path(".env.example")
    if not env_file.exists():
        import pytest
        pytest.skip(".env.example not found in working directory")

    defined: set[str] = set()
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            var_name = line.split("=", 1)[0].strip()
            defined.add(var_name)

    required = {
        "APP_VERSION",
        "BUILD_NUMBER",
        "ENVIRONMENT",
        "PORT",
        "FLASK_DEBUG",
        "AI_PROVIDER",
        "AI_MODEL",
        "METRICS_TOKEN",      # was missing — caused CI failure
        "MONITOR_TOKEN",
        "TARGET_CLOUD",
        "AWS_REGION",
    }

    missing = required - defined
    assert not missing, (
        f".env.example is missing these required variables:\n"
        + "\n".join(f"  • {v}" for v in sorted(missing))
        + "\n\nAdd them so CI and new developers don't miss them."
    )