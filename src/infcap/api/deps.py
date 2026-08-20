"""Dependências compartilhadas pelas rotas.

Os recursos são criados uma vez no ``lifespan`` e ficam em ``app.state``. Passar
por ``Depends`` em vez de ler o estado direto nas rotas mantém os testes capazes
de substituir cliente e banco sem subir rede.
"""

from __future__ import annotations

import asyncio

import aiosqlite
from fastapi import Request

from infcap.data.binance import BinanceClient


async def get_db(request: Request) -> aiosqlite.Connection:
    conn: aiosqlite.Connection = request.app.state.db
    return conn


async def get_binance(request: Request) -> BinanceClient:
    client: BinanceClient = request.app.state.binance
    return client


async def get_sync_lock(request: Request) -> asyncio.Lock:
    lock: asyncio.Lock = request.app.state.sync_lock
    return lock
