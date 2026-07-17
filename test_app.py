from app import application


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


def test_monitor_status_receiver():
    client = application.test_client()
    response = client.post(
        "/monitor/status",
        json={"status": "Approved", "tokens": 123, "requests": 1},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    # The agent state should now reflect "approved".
    status = client.get("/agent/status").get_json()
    assert status["status"] == "Approved"
