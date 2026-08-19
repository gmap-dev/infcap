from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from infcap.app import create_app
from infcap.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="local", log_level="debug")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
