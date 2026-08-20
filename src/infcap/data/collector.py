"""Coleta incremental: liga o cliente da exchange ao cache SQLite.

Esta é a camada que torna o serviço idempotente. Ela pergunta ao cache qual foi
o último candle conhecido, pede à exchange só o que falta, grava página a página
e registra o rastro de frescor do ativo — inclusive quando a coleta falha.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import aiosqlite

from infcap.data.binance import (
    INTERVAL_MS,
    BinanceClient,
    BinanceError,
    SymbolNotListedError,
)
from infcap.storage.db import last_open_time, record_metadata, upsert_klines

logger = logging.getLogger(__name__)

SOURCE: str = "binance"


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Resumo de uma coleta. ``written`` conta candles enviadas ao cache."""

    symbol: str
    interval: str
    written: int
    last_open_time: int | None
    from_cache: bool


def _now_ms() -> int:
    return int(time.time() * 1000)


async def sync_klines(
    conn: aiosqlite.Connection,
    client: BinanceClient,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int | None = None,
) -> SyncResult:
    """Busca da exchange só o trecho ausente e grava incrementalmente.

    O ponto de partida é ``max(start_ms, último_conhecido + 1 intervalo)``, o que
    torna a chamada repetida barata: com o cache quente, nada é pedido de novo.

    Erros da Binance são registrados em ``asset_metadata`` antes de subir, para
    que a ausência de dado nunca seja confundida com dado nunca buscado.
    """
    if interval not in INTERVAL_MS:
        raise ValueError(f"intervalo não suportado: {interval}")

    cached = await last_open_time(conn, symbol, interval)
    cursor = start_ms if cached is None else max(start_ms, cached + INTERVAL_MS[interval])
    latest = cached
    written = 0

    if end_ms is not None and cursor > end_ms:
        # Janela pedida já está inteiramente em cache.
        await record_metadata(conn, symbol, SOURCE, "LISTED", _now_ms(), latest, None)
        return SyncResult(symbol, interval, 0, latest, from_cache=True)

    try:
        async for page in client.iter_klines(symbol, interval, cursor, end_ms):
            written += await upsert_klines(conn, page)
            latest = page[-1].open_time
    except SymbolNotListedError as exc:
        logger.warning("símbolo não listado", extra={"symbol": symbol, "source": SOURCE})
        await record_metadata(
            conn, symbol, SOURCE, "NOT_LISTED", _now_ms(), latest, str(exc) or symbol
        )
        raise
    except BinanceError as exc:
        logger.warning(
            "falha na coleta", extra={"symbol": symbol, "source": SOURCE, "error": str(exc)}
        )
        await record_metadata(conn, symbol, SOURCE, "LISTED", _now_ms(), latest, str(exc))
        raise

    await record_metadata(conn, symbol, SOURCE, "LISTED", _now_ms(), latest, None)
    return SyncResult(symbol, interval, written, latest, from_cache=written == 0)
