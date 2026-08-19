"""Testes do cliente Binance com transporte simulado. Nenhum acesso à rede."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

from infcap.data.binance import BinanceClient, SymbolNotListedError

DAY_MS = 86_400_000
T0 = 1_704_067_200_000


def raw_kline(open_time: int, close: float = 100.0) -> list[Any]:
    """Formato posicional cru da Binance."""
    return [
        open_time,
        f"{close:.8f}",
        f"{close * 1.02:.8f}",
        f"{close * 0.98:.8f}",
        f"{close:.8f}",
        "1234.50000000",
        open_time + DAY_MS - 1,
        "1000000.00000000",
        4321,
        "600.00000000",
        "500000.00000000",
        "0",
    ]


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
    assert client._guard.used == 42
