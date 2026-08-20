"""Rotas de domínio do infcap: candles OHLCV servidos a partir do cache local.

A rota de klines é read-through: garante que a janela pedida esteja no cache
(buscando na exchange só o trecho ausente) e então responde a partir do disco.
Chamar duas vezes com a mesma janela devolve o mesmo resultado sem tráfego novo.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, get_args

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from infcap.api.deps import get_binance, get_db, get_sync_lock
from infcap.data.binance import (
    BinanceClient,
    BinanceError,
    BinanceUnavailableError,
    Interval,
    SymbolNotListedError,
)
from infcap.data.collector import sync_klines
from infcap.storage.db import Kline, read_klines

router = APIRouter(prefix="/v1", tags=["infcap"])


class ServiceInfo(BaseModel):
    name: str
    description: str
    intervals: list[str]


class Candle(BaseModel):
    """Candle normalizada. Todos os tempos em epoch ms UTC."""

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int


class KlineWindow(BaseModel):
    symbol: str
    interval: str
    count: int
    fetched: int = Field(description="Candles trazidas da exchange nesta chamada")
    candles: list[Candle]


def _to_candle(k: Kline) -> Candle:
    return Candle(
        open_time=k.open_time,
        open=k.open,
        high=k.high,
        low=k.low,
        close=k.close,
        volume=k.volume,
        close_time=k.close_time,
        quote_volume=k.quote_volume,
        trades=k.trades,
    )


@router.get("/", response_model=ServiceInfo)
async def root() -> ServiceInfo:
    return ServiceInfo(
        name="infcap",
        description="Candles OHLCV de exchanges de cripto com cache local em SQLite",
        intervals=[str(i) for i in get_args(Interval)],
    )


@router.get("/klines", response_model=KlineWindow)
async def list_klines(
    *,
    symbol: Annotated[str, Query(min_length=2, max_length=20, pattern=r"^[A-Z0-9]+$")],
    interval: Interval,
    start: Annotated[int, Query(ge=0, description="Início da janela, epoch ms UTC")],
    end: Annotated[int | None, Query(ge=0, description="Fim da janela, epoch ms UTC")] = None,
    refresh: Annotated[bool, Query(description="Consultar a exchange antes de responder")] = True,
    conn: Annotated[aiosqlite.Connection, Depends(get_db)],
    client: Annotated[BinanceClient, Depends(get_binance)],
    lock: Annotated[asyncio.Lock, Depends(get_sync_lock)],
) -> KlineWindow:
    """Serve a janela pedida, completando o cache na exchange quando necessário.

    ``refresh=false`` responde só o que já está em disco — útil para não pagar
    latência de rede em consulta a período histórico já consolidado.
    """
    if end is not None and end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "end precisa ser maior ou igual a start"
        )

    fetched = 0
    if refresh:
        try:
            async with lock:
                result = await sync_klines(conn, client, symbol, interval, start, end)
            fetched = result.written
        except SymbolNotListedError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"{symbol} não está listado no spot da Binance",
            ) from exc
        except BinanceUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        except BinanceError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    rows = await read_klines(conn, symbol, interval, start, end)
    return KlineWindow(
        symbol=symbol,
        interval=interval,
        count=len(rows),
        fetched=fetched,
        candles=[_to_candle(k) for k in rows],
    )
