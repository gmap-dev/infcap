from pathlib import Path

from fastapi.testclient import TestClient

from infcap.app import create_app
from infcap.config import Settings


def test_docs_expostos_fora_de_producao(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_docs_desabilitados_em_producao(tmp_path: Path) -> None:
    app = create_app(Settings(environment="production", database_path=tmp_path / "infcap.db"))

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_lifespan_publica_os_recursos(client: TestClient) -> None:
    """O client e o cache existem enquanto a aplicação está de pé."""
    state = client.app.state  # type: ignore[attr-defined]

    assert state.db is not None
    assert state.binance is not None
    assert state.sync_lock is not None
