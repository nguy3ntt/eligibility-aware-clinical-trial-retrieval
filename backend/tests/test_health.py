"""Foundation API tests."""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_discloses_research_status() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "foundation scaffold"
    assert "not medical advice" in response.json()["safety"].lower()
