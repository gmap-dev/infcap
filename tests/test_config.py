import pytest
from pydantic import ValidationError

from infcap.config import Settings


def test_le_variaveis_com_prefixo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFCAP_PORT", "9001")
    monkeypatch.setenv("INFCAP_ENVIRONMENT", "staging")

    settings = Settings()

    assert settings.port == 9001
    assert settings.environment == "staging"
    assert settings.is_production is False


def test_porta_fora_do_intervalo_falha_na_inicializacao() -> None:
    with pytest.raises(ValidationError):
        Settings(port=70000)


def test_ambiente_invalido_falha_na_inicializacao() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod")  # type: ignore[arg-type]
