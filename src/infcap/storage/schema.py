"""Schema do cache local.

Contrato temporal do INFCAP: todo timestamp persistido é epoch em
milissegundos, UTC. A agregação em dia-calendário de ``America/Sao_Paulo``
acontece na camada de análise, nunca no disco.
"""

from __future__ import annotations

from typing import Final

import aiosqlite

SCHEMA_VERSION: Final = 1

PRAGMAS: Final = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)

DDL: Final = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS klines (
    symbol       TEXT    NOT NULL,
    interval     TEXT    NOT NULL,
    open_time    INTEGER NOT NULL,
    open         REAL    NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    close        REAL    NOT NULL,
    volume       REAL    NOT NULL,
    close_time   INTEGER NOT NULL,
    quote_volume REAL    NOT NULL,
    trades       INTEGER NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_klines_symbol_time
    ON klines (symbol, interval, open_time DESC);

CREATE TABLE IF NOT EXISTS asset_metadata (
    symbol               TEXT PRIMARY KEY,
    source               TEXT    NOT NULL,
    listing_status       TEXT    NOT NULL,
    last_fetch_at        INTEGER,
    last_kline_open_time INTEGER,
    last_error           TEXT,
    CHECK (source IN ('binance', 'hyperliquid')),
    CHECK (listing_status IN ('LISTED', 'NOT_LISTED'))
);
"""


async def init_db(conn: aiosqlite.Connection) -> None:
    """Aplica pragmas e cria o schema. Idempotente."""
    for pragma in PRAGMAS:
        await conn.execute(pragma)
    await conn.executescript(DDL)
    await conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('version', ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    await conn.commit()


async def get_schema_version(conn: aiosqlite.Connection) -> int | None:
    async with conn.execute("SELECT value FROM schema_meta WHERE key = 'version'") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else None
