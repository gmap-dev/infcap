"""Testes da coleta incremental: cache + cliente, sem rede."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import aiosqlite
import httpx2
import pytest
import pytest_asyncio

from factories import DAY_MS, T0, raw_kline
from infcap.data.binance import BinanceClient
from infcap.data.collector import sync_klines
from infcap.storage.db import connect, read_klines, upsert_klines

Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest_asyncio.fixture
async def conn(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    async with connect(tmp_path / "cache.db") as connection:
        yield connection


def client_with(handler: Handler) -> BinanceClient:
    return BinanceClient(client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


async def metadata(conn: aiosqlite.Connection, symbol: str) -> dict[str, Any]:
    async with conn.execute(
        "SELECT source, listing_status, last_fetch_at, last_kline_open_time, last_error "
        "FROM asset_metadata WHERE symbol = ?",
        (symbol,),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    keys = ("source", "listing_status", "last_fetch_at", "last_kline_open_time", "last_error")
    return dict(zip(keys, row, strict=True))


@pytest.mark.asyncio
async def test_grava_e_registra_frescor(conn: aiosqlite.Connection) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[raw_kline(T0), raw_kline(T0 + DAY_MS)])

    async with client_with(handler) as client:
        result = await sync_klines(conn, client, "BTCUSDT", "1d", T0)

    assert result.written == 2
    assert result.last_open_time == T0 + DAY_MS
    assert len(await read_klines(conn, "BTCUSDT", "1d")) == 2

    meta = await metadata(conn, "BTCUSDT")
    assert meta["listing_status"] == "LISTED"
    assert meta["source"] == "binance"
    assert meta["last_error"] is None
    assert meta["last_kline_open_time"] == T0 + DAY_MS
    assert meta["last_fetch_at"] > 0


@pytest.mark.asyncio
async def test_retoma_do_ultimo_candle_conhecido(conn: aiosqlite.Connection) -> None:
    """O ponto de partida é o cache, não o ``start`` do chamador."""
    seen: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(int(request.url.params["startTime"]))
        return httpx2.Response(200, json=[raw_kline(T0 + 3 * DAY_MS)])

    async with client_with(handler) as first:
        await sync_klines(conn, first, "BTCUSDT", "1d", T0)
    seen.clear()

    def handler2(request: httpx2.Request) -> httpx2.Response:
        seen.append(int(request.url.params["startTime"]))
        return httpx2.Response(200, json=[])

    async with client_with(handler2) as second:
        await sync_klines(conn, second, "BTCUSDT", "1d", T0)

    assert seen == [T0 + 4 * DAY_MS]


@pytest.mark.asyncio
async def test_janela_ja_em_cache_nao_toca_a_rede(conn: aiosqlite.Connection) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        raise AssertionError("não deveria fazer request")

    from infcap.storage.db import Kline

    await upsert_klines(
        conn,
        [
            Kline(
                symbol="BTCUSDT",
                interval="1d",
                open_time=T0,
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1.0,
                close_time=T0 + DAY_MS - 1,
                quote_volume=1.0,
                trades=1,
            )
        ],
    )

    async with client_with(handler) as client:
        result = await sync_klines(conn, client, "BTCUSDT", "1d", T0, T0)

    assert result.written == 0
    assert result.from_cache is True


@pytest.mark.asyncio
async def test_repetir_a_coleta_e_idempotente(conn: aiosqlite.Connection) -> None:
    """Reprocessar a mesma janela não duplica candle: a PK absorve."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        start = int(request.url.params["startTime"])
        if start > T0:
            return httpx2.Response(200, json=[])
        return httpx2.Response(200, json=[raw_kline(T0)])

    async with client_with(handler) as client:
        await sync_klines(conn, client, "BTCUSDT", "1d", T0)
        await sync_klines(conn, client, "BTCUSDT", "1d", T0)

    assert len(await read_klines(conn, "BTCUSDT", "1d")) == 1


@pytest.mark.asyncio
async def test_simbolo_nao_listado_marca_metadata_e_sobe(conn: aiosqlite.Connection) -> None:
    """Ausência estrutural fica registrada — não se confunde com nunca buscado."""
    from infcap.data.binance import SymbolNotListedError

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    async with client_with(handler) as client:
        with pytest.raises(SymbolNotListedError):
            await sync_klines(conn, client, "HYPEUSDT", "1d", T0)

    meta = await metadata(conn, "HYPEUSDT")
    assert meta["listing_status"] == "NOT_LISTED"
    assert meta["last_error"]


@pytest.mark.asyncio
async def test_falha_da_exchange_registra_erro_e_sobe(conn: aiosqlite.Connection) -> None:
    from infcap.data.binance import BinanceError

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"code": -1100, "msg": "Illegal characters."})

    async with client_with(handler) as client:
        with pytest.raises(BinanceError):
            await sync_klines(conn, client, "BTCUSDT", "1d", T0)

    meta = await metadata(conn, "BTCUSDT")
    assert meta["listing_status"] == "LISTED"
    assert "1100" in str(meta["last_error"])


@pytest.mark.asyncio
async def test_intervalo_invalido_rejeitado(conn: aiosqlite.Connection) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover
        raise AssertionError("não deveria fazer request")

    async with client_with(handler) as client:
        with pytest.raises(ValueError, match="3w"):
            await sync_klines(conn, client, "BTCUSDT", "3w", T0)
