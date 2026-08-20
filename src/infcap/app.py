"""Fábrica da aplicação FastAPI."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from infcap import __version__
from infcap.api import health, routes
from infcap.config import Settings, get_settings
from infcap.data.binance import BinanceClient
from infcap.logging import configure_logging
from infcap.storage.db import connect

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre e fecha os recursos de longa duração: cache SQLite e cliente HTTP.

    Ambos vivem pelo processo inteiro. Abrir conexão por request desperdiçaria o
    pool de sockets e recriaria o schema a cada chamada.
    """
    settings: Settings = app.state.settings
    logger.info("serviço iniciando", extra={"environment": settings.environment})

    async with AsyncExitStack() as stack:
        app.state.db = await stack.enter_async_context(connect(settings.database_path))
        app.state.binance = await stack.enter_async_context(
            BinanceClient(
                base_url=settings.binance_base_url,
                timeout=settings.request_timeout,
            )
        )
        # Uma conexão SQLite só suporta um escritor: serializa as coletas.
        app.state.sync_lock = asyncio.Lock()
        logger.info("recursos prontos", extra={"database": str(settings.database_path)})
        yield

    logger.info("serviço encerrando")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Constrói a aplicação. Recebe ``settings`` explicitamente para facilitar testes."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="infcap",
        version=__version__,
        # Documentação interativa fica fora do ar em produção.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.include_router(health.router)
    app.include_router(routes.router)

    return app
