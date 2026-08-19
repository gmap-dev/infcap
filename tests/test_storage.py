"""Testes do cache SQLite. Nenhum acesso à rede."""

from __future__ import annotations

from dataclasses import replace

import pytest

from infcap.storage.db import (
    Kline,
    connect,
    last_open_time,
    read_klines,
    record_metadata,
    upsert_klines,
)
from infcap.storage.schema import SCHEMA_VERSION, get_schema_version

DAY_MS = 86_400_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z


def make_kline(offset_days: int, close: float = 100.0) -> Kline:
    open_time = T0 + offset_days * DAY_MS
    return Kline(
        symbol="BTCUSDT",
        interval="1d",
        open_time=open_time,
        open=close,
        high=close * 1.02,
        low=close * 0.98,
        close=close,
        volume=1234.5,
        close_time=open_time + DAY_MS - 1,
        quote_volume=1_000_000.0,
        trades=4321,
    )


@pytest.mark.asyncio
async def test_schema_is_versioned() -> None:
    async with connect(":memory:") as conn:
        assert await get_schema_version(conn) == SCHEMA_VERSION


@pytest.mark.asyncio
async def test_init_is_idempotent() -> None:
    from infcap.storage.schema import init_db

    async with connect(":memory:") as conn:
        await init_db(conn)
        assert await get_schema_version(conn) == SCHEMA_VERSION


@pytest.mark.asyncio
async def test_upsert_and_read_roundtrip() -> None:
    async with connect(":memory:") as conn:
        klines = [make_kline(i, close=100.0 + i) for i in range(5)]
        await upsert_klines(conn, klines)
        got = await read_klines(conn, "BTCUSDT", "1d")
        assert [k.open_time for k in got] == [k.open_time for k in klines]
        assert got[3].close == pytest.approx(103.0)


@pytest.mark.asyncio
async def test_duplicate_open_time_does_not_duplicate_row() -> None:
    """A PK composta garante idempotência do refetch de um gap."""
    async with connect(":memory:") as conn:
        await upsert_klines(conn, [make_kline(0)])
        await upsert_klines(conn, [make_kline(0)])
        assert len(await read_klines(conn, "BTCUSDT", "1d")) == 1


@pytest.mark.asyncio
async def test_same_open_time_different_interval_coexists() -> None:
    async with connect(":memory:") as conn:
        daily = make_kline(0)
        hourly = replace(daily, interval="1h")
        await upsert_klines(conn, [daily, hourly])
        assert len(await read_klines(conn, "BTCUSDT", "1d")) == 1
        assert len(await read_klines(conn, "BTCUSDT", "1h")) == 1


@pytest.mark.asyncio
async def test_read_klines_respects_range() -> None:
    async with connect(":memory:") as conn:
        await upsert_klines(conn, [make_kline(i) for i in range(10)])
        got = await read_klines(conn, "BTCUSDT", "1d", start=T0 + 2 * DAY_MS, end=T0 + 4 * DAY_MS)
        assert len(got) == 3


@pytest.mark.asyncio
async def test_last_open_time_drives_incremental_fetch() -> None:
    async with connect(":memory:") as conn:
        assert await last_open_time(conn, "BTCUSDT", "1d") is None
        await upsert_klines(conn, [make_kline(i) for i in range(3)])
        assert await last_open_time(conn, "BTCUSDT", "1d") == T0 + 2 * DAY_MS


@pytest.mark.asyncio
async def test_metadata_upsert_preserves_last_kline_when_absent() -> None:
    """Um erro de fetch não pode apagar o rastro da última candle boa."""
    async with connect(":memory:") as conn:
        await record_metadata(conn, "BTCUSDT", "binance", "LISTED", T0, T0 - DAY_MS)
        await record_metadata(conn, "BTCUSDT", "binance", "LISTED", T0 + 1000, None, "timeout")
        async with conn.execute(
            "SELECT last_kline_open_time, last_error FROM asset_metadata WHERE symbol = ?",
            ("BTCUSDT",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == T0 - DAY_MS
        assert row[1] == "timeout"


@pytest.mark.asyncio
async def test_metadata_rejects_unknown_source() -> None:
    import aiosqlite

    async with connect(":memory:") as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await record_metadata(conn, "HYPE", "coinbase", "LISTED", T0)
