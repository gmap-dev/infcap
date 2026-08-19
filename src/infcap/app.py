"""Fábrica da aplicação FastAPI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from infcap import __version__
from infcap.api import health, routes
from infcap.config import Settings, get_settings
from infcap.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre e fecha recursos de longa duração (pools, clientes, consumidores)."""
    settings: Settings = app.state.settings
    logger.info("serviço iniciando", extra={"environment": settings.environment})
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
