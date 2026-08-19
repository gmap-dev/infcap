from fastapi.testclient import TestClient

from infcap import __version__


def test_liveness_reporta_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_readiness_reporta_ok_sem_dependencias(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
