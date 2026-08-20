from collections.abc import Callable, Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from infcap.app import create_app
from infcap.config import Settings
from infcap.data.binance import BinanceClient

Handler = Callable[[httpx2.Request], httpx2.Response]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Cada teste recebe um cache próprio — nada escreve no banco do repositório."""
    return Settings(
        environment="local",
        log_level="debug",
        database_path=tmp_path / "infcap.db",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def make_binance() -> Callable[[Handler], BinanceClient]:
    """Constrói um ``BinanceClient`` sobre transporte simulado. Nenhuma rede."""

    def factory(handler: Handler) -> BinanceClient:
        return BinanceClient(client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    return factory
