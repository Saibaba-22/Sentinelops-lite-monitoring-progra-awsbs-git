from app import application
import os

def test_home():
    client = application.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


def test_api():
    client = application.test_client()
    response = client.get("/api")
    assert response.status_code == 200
    data = response.get_json()
    assert data["message"] == "Hello from SentinelOps-Lite!"
    assert data["status"] == "running"


def test_health():
    client = application.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


def test_metrics_endpoint():
    client = application.test_client()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    # Our custom application metrics must be present.
    assert b"app_requests_total" in response.data
    assert b"python_process_cpu_percent" in response.data


def test_api_status():
    client = application.test_client()
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.get_json()
    for section in ("application", "system", "agent", "deployment"):
        assert section in data
    assert data["deployment"]["version"]
    assert "cpu_usage_percent" in data["system"]


def test_agent_status():
    client = application.test_client()
    response = client.get("/agent/status")
    assert response.status_code == 200
    data = response.get_json()
    assert "status" in data

def test_monitor_status_receiver(client, monkeypatch):
    """Verify that an authorized CI-agent monitoring event is accepted."""
    test_monitor_token = "unit-test-monitor-token
    # The Flask endpoint checks this value at request time.
    monkeypatch.setenv("MONITOR_TOKEN", test_monitor_token)
    payload = {
        "agent_name": "test_agent",
        "stage": "pre_deploy",
        "cloud": "aws",
        "status": "approved",
        "decision": "pass",
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "requests": 1,
        "api_key_count": 1,
        "execution_time_seconds": 1.0,
        "api_response_time_seconds": 0.5,
    }
    response = client.post(
        "/monitor/status",
        json=payload,
        headers={
            "X-Monitor-Token": test_monitor_token,
        },
    )
    assert response.status_code == 200
    response_data = response.get_json()
    assert response_data["ok"] is True