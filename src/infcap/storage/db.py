"""Acesso ao cache SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from infcap.storage.schema import init_db


@dataclass(frozen=True, slots=True)
class Kline:
    """Candle normalizada. Todos os tempos em epoch ms UTC."""

    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int


@asynccontextmanager
async def connect(path: Path | str) -> AsyncIterator[aiosqlite.Connection]:
    """Abre conexão com o schema garantido. Use ``:memory:`` nos testes."""
    conn = await aiosqlite.connect(path)
    try:
        await init_db(conn)
        yield conn
    finally:
        await conn.close()


async def upsert_klines(conn: aiosqlite.Connection, klines: Sequence[Kline]) -> int:
    """Insere candles ignorando duplicatas pela PK."""
    if not klines:
        return 0
    await conn.executemany(
        "INSERT INTO klines (symbol, interval, open_time, open, high, low, close, "
        "volume, close_time, quote_volume, trades) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol, interval, open_time) DO NOTHING",
        [
            (
                k.symbol,
                k.interval,
                k.open_time,
                k.open,
                k.high,
                k.low,
                k.close,
                k.volume,
                k.close_time,
                k.quote_volume,
                k.trades,
            )
            for k in klines
        ],
    )
    await conn.commit()
    return len(klines)


async def last_open_time(conn: aiosqlite.Connection, symbol: str, interval: str) -> int | None:
    """Maior ``open_time`` em cache — ponto de partida do fetch incremental."""
    async with conn.execute(
        "SELECT MAX(open_time) FROM klines WHERE symbol = ? AND interval = ?",
        (symbol, interval),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def read_klines(
    conn: aiosqlite.Connection,
    symbol: str,
    interval: str,
    start: int | None = None,
    end: int | None = None,
) -> list[Kline]:
    """Lê candles em ordem cronológica, com recorte opcional."""
    sql = [
        "SELECT symbol, interval, open_time, open, high, low, close, volume, "
        "close_time, quote_volume, trades FROM klines WHERE symbol = ? AND interval = ?"
    ]
    params: list[object] = [symbol, interval]
    if start is not None:
        sql.append("AND open_time >= ?")
        params.append(start)
    if end is not None:
        sql.append("AND open_time <= ?")
        params.append(end)
    sql.append("ORDER BY open_time ASC")

    async with conn.execute(" ".join(sql), params) as cur:
        rows = await cur.fetchall()
    return [
        Kline(
            symbol=str(r[0]),
            interval=str(r[1]),
            open_time=int(r[2]),
            open=float(r[3]),
            high=float(r[4]),
            low=float(r[5]),
            close=float(r[6]),
            volume=float(r[7]),
            close_time=int(r[8]),
            quote_volume=float(r[9]),
            trades=int(r[10]),
        )
        for r in rows
    ]


async def record_metadata(
    conn: aiosqlite.Connection,
    symbol: str,
    source: str,
    listing_status: str,
    fetched_at_ms: int,
    last_kline_open_time: int | None = None,
    error: str | None = None,
) -> None:
    """Grava o rastro de staleness do ativo."""
    await conn.execute(
        "INSERT INTO asset_metadata (symbol, source, listing_status, last_fetch_at, "
        "last_kline_open_time, last_error) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol) DO UPDATE SET "
        "source = excluded.source, "
        "listing_status = excluded.listing_status, "
        "last_fetch_at = excluded.last_fetch_at, "
        "last_kline_open_time = COALESCE("
        "  excluded.last_kline_open_time, asset_metadata.last_kline_open_time), "
        "last_error = excluded.last_error",
        (symbol, source, listing_status, fetched_at_ms, last_kline_open_time, error),
    )
    await conn.commit()
