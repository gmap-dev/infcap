"""Configuração da aplicação, carregada de variáveis de ambiente."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]
LogLevel = Literal["debug", "info", "warning", "error"]


class Settings(BaseSettings):
    """Configuração lida de variáveis com prefixo ``INFCAP_`` e do arquivo ``.env``.

    Valores inválidos falham na inicialização, não em tempo de request.
    """

    model_config = SettingsConfigDict(
        env_prefix="INFCAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "local"
    log_level: LogLevel = "info"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância única de Settings. O cache é limpo nos testes via ``cache_clear()``."""
    return Settings()
