from fastapi.testclient import TestClient

from infcap import __version__


def test_liveness_reporta_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "checks": {}}


def test_readiness_verifica_o_cache(client: TestClient) -> None:
    """Readiness só é ok se o SQLite responde de verdade."""
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"database": True}


def test_readiness_degrada_sem_cache(client: TestClient) -> None:
    """Cache fora do ar tira a instância do balanceador, sem derrubar o processo."""
    del client.app.state.db  # type: ignore[attr-defined]

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {"database": False}
