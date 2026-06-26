def test_health_endpoint():
    from fastapi.testclient import TestClient

    from ytdb.api.app import create_app

    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "ready" in body

