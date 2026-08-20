"""Testes do cliente Binance com transporte simulado. Nenhum acesso à rede."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

from factories import DAY_MS, T0, raw_kline
from infcap.data.binance import (
    BinanceClient,
    BinanceError,
    BinanceUnavailableError,
    SymbolNotListedError,
    WeightGuard,
)


def client_with(handler: Any) -> BinanceClient:
    return BinanceClient(client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


@pytest.mark.asyncio
async def test_parses_positional_payload() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[raw_kline(T0, 42.0)])

    async with client_with(handler) as client:
        got = await client.fetch_klines("BTCUSDT", "1d", T0)

    assert len(got) == 1
    assert got[0].open_time == T0
    assert got[0].close == pytest.approx(42.0)
    assert got[0].trades == 4321
    assert got[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_paginates_until_short_batch() -> None:
    """Lote cheio implica próxima página; lote curto encerra."""
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        start = int(request.url.params["startTime"])
        calls.append(start)
        if len(calls) == 1:
            rows = [raw_kline(T0 + i * DAY_MS) for i in range(1000)]
        else:
            rows = [raw_kline(T0 + (1000 + i) * DAY_MS) for i in range(3)]
        return httpx2.Response(200, json=rows)

    async with client_with(handler) as client:
        got = await client.fetch_klines("BTCUSDT", "1d", T0)

    assert len(calls) == 2
    assert calls[1] == T0 + 1000 * DAY_MS
    assert len(got) == 1003


@pytest.mark.asyncio
async def test_empty_batch_terminates() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[])

    async with client_with(handler) as client:
        assert await client.fetch_klines("BTCUSDT", "1d", T0) == []


@pytest.mark.asyncio
async def test_invalid_symbol_raises_not_listed() -> None:
    """Contrato do HYPE: ausência estrutural vira erro tipado, sem retry."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    async with client_with(handler) as client:
        with pytest.raises(SymbolNotListedError):
            await client.fetch_klines("HYPEUSDT", "1d", T0)


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds() -> None:
    attempts: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx2.Response(429, headers={"retry-after": "0"})
        return httpx2.Response(200, json=[raw_kline(T0)])

    async with client_with(handler) as client:
        got = await client.fetch_klines("BTCUSDT", "1d", T0)

    assert len(attempts) == 2
    assert len(got) == 1


@pytest.mark.asyncio
async def test_unsupported_interval_rejected_before_any_request() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        raise AssertionError("não deveria fazer request")

    async with client_with(handler) as client:
        with pytest.raises(ValueError):
            await client.fetch_klines("BTCUSDT", "3w", T0)


@pytest.mark.asyncio
async def test_weight_header_is_tracked() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[raw_kline(T0)], headers={"x-mbx-used-weight-1m": "42"})

    client = client_with(handler)
    async with client:
        await client.fetch_klines("BTCUSDT", "1d", T0)
    assert client.used_weight == 42


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Neutraliza o backoff e devolve a sequência de esperas pedidas."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("infcap.data.binance.asyncio.sleep", fake_sleep)
    return delays


@pytest.mark.asyncio
async def test_erro_de_transporte_tem_retry(no_sleep: list[float]) -> None:
    """Timeout e falha de conexão são transitórios: tenta de novo antes de desistir."""
    attempts: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx2.ConnectError("conexão recusada", request=request)
        return httpx2.Response(200, json=[raw_kline(T0)])

    async with client_with(handler) as client:
        got = await client.fetch_klines("BTCUSDT", "1d", T0)

    assert len(attempts) == 3
    assert len(got) == 1
    assert no_sleep == [1.0, 2.0]


@pytest.mark.asyncio
async def test_erro_nao_transporte_do_httpx_tambem_e_embrulhado(no_sleep: list[float]) -> None:
    """``DecodingError`` não é ``TransportError`` — ainda assim não vaza para o chamador."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.DecodingError("corpo ilegível", request=request)

    async with client_with(handler) as client:
        with pytest.raises(BinanceUnavailableError):
            await client.fetch_klines("BTCUSDT", "1d", T0)


@pytest.mark.asyncio
async def test_5xx_tem_retry_e_depois_sucede(no_sleep: list[float]) -> None:
    responses = [503, 500, 200]

    def handler(request: httpx2.Request) -> httpx2.Response:
        code = responses.pop(0)
        if code == 200:
            return httpx2.Response(200, json=[raw_kline(T0)])
        return httpx2.Response(code)

    async with client_with(handler) as client:
        got = await client.fetch_klines("BTCUSDT", "1d", T0)

    assert len(got) == 1
    assert responses == []


@pytest.mark.asyncio
async def test_tentativas_esgotadas_viram_unavailable(no_sleep: list[float]) -> None:
    """Falha persistente sobe com tipo próprio, preservando a causa original."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503)

    async with client_with(handler) as client:
        with pytest.raises(BinanceUnavailableError) as excinfo:
            await client.fetch_klines("BTCUSDT", "1d", T0)

    assert "4 tentativas" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, BinanceUnavailableError)
    assert len(no_sleep) == 4


@pytest.mark.asyncio
async def test_400_generico_vira_binance_error() -> None:
    """Só ``-1121`` é NOT_LISTED; o resto é erro de requisição, não de listagem."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"code": -1100, "msg": "Illegal characters."})

    async with client_with(handler) as client:
        with pytest.raises(BinanceError) as excinfo:
            await client.fetch_klines("BTCUSDT", "1d", T0)

    assert not isinstance(excinfo.value, SymbolNotListedError)


@pytest.mark.asyncio
async def test_4xx_fora_do_400_vira_binance_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, text="WAF")

    async with client_with(handler) as client:
        with pytest.raises(BinanceError, match="403"):
            await client.fetch_klines("BTCUSDT", "1d", T0)


@pytest.mark.asyncio
async def test_corpo_nao_json_vira_binance_error() -> None:
    """Página de erro de gateway com status 200 não pode virar ``JSONDecodeError``."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>502 Bad Gateway</html>")

    async with client_with(handler) as client:
        with pytest.raises(BinanceError, match="não-JSON"):
            await client.fetch_klines("BTCUSDT", "1d", T0)


@pytest.mark.asyncio
async def test_end_ms_limita_a_janela() -> None:
    """``endTime`` vai na query e o cursor para ao ultrapassar o fim pedido."""
    seen: list[dict[str, str]] = []
    end = T0 + 1500 * DAY_MS

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(dict(request.url.params))
        start = int(request.url.params["startTime"])
        return httpx2.Response(200, json=[raw_kline(start + i * DAY_MS) for i in range(1000)])

    async with client_with(handler) as client:
        got = await client.fetch_klines("BTCUSDT", "1d", T0, end)

    assert all(p["endTime"] == str(end) for p in seen)
    # Segunda página começa em T0+1000d; a terceira passaria de `end` e não acontece.
    assert [p["startTime"] for p in seen] == [str(T0), str(T0 + 1000 * DAY_MS)]
    assert len(got) == 2000


@pytest.mark.asyncio
async def test_iter_klines_entrega_pagina_a_pagina() -> None:
    """O streaming existe para não materializar o intervalo inteiro."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        start = int(request.url.params["startTime"])
        if start == T0:
            return httpx2.Response(200, json=[raw_kline(T0 + i * DAY_MS) for i in range(1000)])
        return httpx2.Response(200, json=[raw_kline(start)])

    pages: list[int] = []
    async with client_with(handler) as client:
        async for page in client.iter_klines("BTCUSDT", "1d", T0):
            pages.append(len(page))

    assert pages == [1000, 1]


@pytest.mark.asyncio
async def test_intervalo_invalido_falha_na_chamada_nao_na_iteracao() -> None:
    """``iter_klines`` valida na hora — o erro aparece onde foi cometido."""

    def handler(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        raise AssertionError("não deveria fazer request")

    async with client_with(handler) as client:
        with pytest.raises(ValueError, match="3w"):
            client.iter_klines("BTCUSDT", "3w", T0)


@pytest.mark.asyncio
async def test_fecha_apenas_o_client_que_criou() -> None:
    own = BinanceClient(base_url="http://exemplo.invalido")
    async with own:
        pass
    assert own._client.is_closed

    injected = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(200)))
    async with BinanceClient(client=injected):
        pass
    assert not injected.is_closed
    await injected.aclose()


@pytest.mark.asyncio
async def test_guard_dorme_o_que_resta_da_janela(no_sleep: list[float]) -> None:
    guard = WeightGuard(ceiling=10)
    guard.used = 10

    await guard.wait_if_needed()

    assert len(no_sleep) == 1
    assert 55.0 < no_sleep[0] <= 60.0
    assert guard.used == 0


@pytest.mark.asyncio
async def test_guard_nao_dorme_abaixo_do_teto(no_sleep: list[float]) -> None:
    guard = WeightGuard(ceiling=10)
    guard.used = 9

    await guard.wait_if_needed()

    assert no_sleep == []


def test_guard_ignora_header_ausente_ou_invalido() -> None:
    guard = WeightGuard(ceiling=10)
    guard.observe(httpx2.Headers({"x-mbx-used-weight-1m": "8"}))
    guard.observe(httpx2.Headers({}))
    guard.observe(httpx2.Headers({"x-mbx-used-weight-1m": "n/a"}))

    assert guard.used == 8


def test_guard_detecta_virada_de_janela() -> None:
    """Contador caindo significa janela nova, não peso liberado no meio da atual."""
    guard = WeightGuard(ceiling=10)
    guard.observe(httpx2.Headers({"x-mbx-used-weight-1m": "9"}))
    guard.observe(httpx2.Headers({"x-mbx-used-weight-1m": "2"}))

    assert guard.used == 2
