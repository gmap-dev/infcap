from fastapi.testclient import TestClient

from infcap.app import create_app
from infcap.config import Settings


def test_docs_expostos_fora_de_producao(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_docs_desabilitados_em_producao() -> None:
    app = create_app(Settings(environment="production"))

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
