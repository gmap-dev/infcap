"""Testes da rota de klines: client, cache e mapeamento de erro para HTTP."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from factories import DAY_MS, T0, raw_kline
from infcap.api.deps import get_binance
from infcap.app import create_app
from infcap.config import Settings
from infcap.data.binance import BinanceClient

Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest.fixture
def app_with(settings: Settings) -> Callable[[Handler], Iterator[TestClient]]:
    """Sobe a aplicação real substituindo só o transporte HTTP do client."""

    def factory(handler: Handler) -> Iterator[TestClient]:
        app = create_app(settings)
        fake = BinanceClient(client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
        app.dependency_overrides[get_binance] = lambda: fake
        with TestClient(app) as test_client:
            yield test_client

    return factory


def serving(handler: Handler, app_with: Callable[[Handler], Iterator[TestClient]]) -> TestClient:
    return next(app_with(handler))


def test_root_anuncia_os_intervalos_suportados(client: TestClient) -> None:
    body = client.get("/v1/").json()

    assert body["name"] == "infcap"
    assert body["intervals"] == ["1m", "5m", "15m", "1h", "4h", "1d"]


def test_serve_candles_da_exchange_e_depois_do_cache(
    app_with: Callable[[Handler], Iterator[TestClient]],
) -> None:
    """Primeira chamada busca; a segunda responde igual sem pedir nada de novo."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(int(request.url.params["startTime"]))
        if int(request.url.params["startTime"]) > T0:
            return httpx2.Response(200, json=[])
        return httpx2.Response(200, json=[raw_kline(T0, 42.0), raw_kline(T0 + DAY_MS, 43.0)])

    for test_client in app_with(handler):
        first = test_client.get(
            "/v1/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": T0}
        )
        second = test_client.get(
            "/v1/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": T0}
        )

        assert first.status_code == 200
        body = first.json()
        assert body["count"] == 2
        assert body["fetched"] == 2
        assert body["candles"][0]["close"] == pytest.approx(42.0)
        assert body["candles"][0]["open_time"] == T0

        assert second.status_code == 200
        assert second.json()["fetched"] == 0
        assert second.json()["candles"] == body["candles"]


def test_refresh_false_nao_toca_a_exchange(
    app_with: Callable[[Handler], Iterator[TestClient]],
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        raise AssertionError("não deveria fazer request")

    for test_client in app_with(handler):
        response = test_client.get(
            "/v1/klines",
            params={"symbol": "BTCUSDT", "interval": "1d", "start": T0, "refresh": "false"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "BTCUSDT",
        "interval": "1d",
        "count": 0,
        "fetched": 0,
        "candles": [],
    }


def test_simbolo_nao_listado_vira_404(
    app_with: Callable[[Handler], Iterator[TestClient]],
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    for test_client in app_with(handler):
        response = test_client.get(
            "/v1/klines", params={"symbol": "HYPEUSDT", "interval": "1d", "start": T0}
        )

    assert response.status_code == 404
    assert "HYPEUSDT" in response.json()["detail"]


def test_exchange_indisponivel_vira_503(
    app_with: Callable[[Handler], Iterator[TestClient]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha transitória da Binance não é erro nosso: 503, não 500."""

    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("infcap.data.binance.asyncio.sleep", no_sleep)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503)

    for test_client in app_with(handler):
        response = test_client.get(
            "/v1/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": T0}
        )

    assert response.status_code == 503


def test_erro_de_requisicao_vira_502(
    app_with: Callable[[Handler], Iterator[TestClient]],
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"code": -1100, "msg": "Illegal characters."})

    for test_client in app_with(handler):
        response = test_client.get(
            "/v1/klines", params={"symbol": "BTCUSDT", "interval": "1d", "start": T0}
        )

    assert response.status_code == 502


def test_janela_invertida_e_rejeitada(client: TestClient) -> None:
    response = client.get(
        "/v1/klines",
        params={"symbol": "BTCUSDT", "interval": "1d", "start": T0, "end": T0 - 1},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("params", "motivo"),
    [
        ({"symbol": "BTCUSDT", "interval": "3w", "start": T0}, "intervalo fora do enum"),
        ({"symbol": "btcusdt", "interval": "1d", "start": T0}, "símbolo minúsculo"),
        ({"symbol": "B", "interval": "1d", "start": T0}, "símbolo curto demais"),
        ({"symbol": "BTCUSDT", "interval": "1d", "start": -1}, "start negativo"),
    ],
)
def test_parametros_invalidos_falham_antes_de_qualquer_request(
    client: TestClient, params: dict[str, str | int], motivo: str
) -> None:
    assert client.get("/v1/klines", params=params).status_code == 422, motivo
