"""Cliente da API pública da Binance (spot).

Escopo: apenas ``/api/v3/klines``. Sem chave de API, sem endpoints privados.

Sobre limites: a Binance controla por peso por minuto e reporta o contador no
header ``X-MBX-USED-WEIGHT-1M``. O limitador aqui acompanha esse contador e faz
backoff em 429/418 respeitando ``Retry-After``. O limite ratificado de 6/hora e
20/dia pertence à camada de análise por modelo, não a este cliente.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Final

import httpx2

from infcap.storage.db import Kline

BASE_URL: Final = "https://api.binance.com"
MAX_LIMIT: Final = 1000
WEIGHT_CEILING: Final = 1100

INTERVAL_MS: Final[dict[str, int]] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class BinanceError(RuntimeError):
    """Falha irrecuperável ao conversar com a Binance."""


class SymbolNotListedError(BinanceError):
    """Símbolo ausente do spot da Binance — contrato NOT_LISTED."""


@dataclass(slots=True)
class WeightGuard:
    """Acompanha o peso reportado pela Binance e pausa antes de estourar."""

    used: int = 0
    ceiling: int = WEIGHT_CEILING

    def observe(self, headers: httpx2.Headers) -> None:
        raw = headers.get("x-mbx-used-weight-1m")
        if raw is not None and raw.isdigit():
            self.used = int(raw)

    async def wait_if_needed(self) -> None:
        if self.used >= self.ceiling:
            await asyncio.sleep(60)
            self.used = 0


class BinanceClient:
    """Busca klines com paginação. Instancie via ``async with``."""

    def __init__(
        self,
        client: httpx2.AsyncClient | None = None,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx2.AsyncClient(timeout=timeout)
        self._guard = WeightGuard()
        self._max_retries = max_retries

    async def __aenter__(self) -> BinanceClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        """GET com backoff em 429/418 e erro tipado para símbolo inexistente."""
        for attempt in range(self._max_retries):
            await self._guard.wait_if_needed()
            response = await self._client.get(f"{self._base_url}{path}", params=params)
            self._guard.observe(response.headers)

            if response.status_code in (429, 418):
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after else 2.0 ** (attempt + 1)
                await asyncio.sleep(delay)
                continue

            if response.status_code == 400:
                body = response.json()
                if isinstance(body, dict) and body.get("code") == -1121:
                    raise SymbolNotListedError(str(params.get("symbol")))
                raise BinanceError(f"400 da Binance: {body}")

            response.raise_for_status()
            return response.json()

        raise BinanceError(f"limite de tentativas esgotado em {path}")

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> list[Kline]:
        """Busca candles de ``start_ms`` (inclusive) até ``end_ms``, paginando.

        Tempos em epoch ms UTC. A última candle pode estar aberta; cabe ao
        chamador descartá-la se precisar apenas de períodos fechados.
        """
        if interval not in INTERVAL_MS:
            raise ValueError(f"intervalo não suportado: {interval}")

        step = INTERVAL_MS[interval]
        cursor = start_ms
        out: list[Kline] = []

        while True:
            params: dict[str, Any] = {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "limit": MAX_LIMIT,
            }
            if end_ms is not None:
                params["endTime"] = end_ms

            batch = await self._get("/api/v3/klines", params)
            if not batch:
                break

            out.extend(_to_kline(symbol, interval, row) for row in batch)

            if len(batch) < MAX_LIMIT:
                break
            cursor = int(batch[-1][0]) + step
            if end_ms is not None and cursor > end_ms:
                break

        return out


def _to_kline(symbol: str, interval: str, row: list[Any]) -> Kline:
    """Converte a lista posicional da Binance em ``Kline`` tipada."""
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=int(row[6]),
        quote_volume=float(row[7]),
        trades=int(row[8]),
    )
