"""Cliente da API pública da Binance (spot).

Escopo: apenas ``/api/v3/klines``. Sem chave de API, sem endpoints privados.

Contrato de erro: tudo que sai daqui é ``BinanceError`` ou subclasse. Falhas de
transporte, 5xx e corpo ilegível são reempacotados — nada do httpx2 vaza.

Limites: a Binance controla por peso por minuto e reporta o contador no header
``X-MBX-USED-WEIGHT-1M``. O limite ratificado de 6/hora e 20/dia pertence à
camada de análise por modelo, não a este cliente.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import httpx2

from infcap.storage.db import Kline

BASE_URL: Final = "https://api.binance.com"
MAX_LIMIT: Final = 1000
WINDOW_SECONDS: Final = 60.0
RETRYABLE_STATUS: Final = frozenset({418, 429, 500, 502, 503, 504})

# Teto conservador sobre o limite por minuto publicado pela Binance.
# Conferir contra a documentação vigente antes de alterar.
WEIGHT_CEILING: Final = 1100

Interval = Literal["1m", "5m", "15m", "1h", "4h", "1d"]

INTERVAL_MS: Final[dict[Interval, int]] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class BinanceError(RuntimeError):
    """Falha ao conversar com a Binance. Raiz de tudo que este módulo levanta."""


class SymbolNotListedError(BinanceError):
    """Símbolo ausente do spot da Binance — contrato NOT_LISTED, sem retry."""


class BinanceUnavailableError(BinanceError):
    """Falha transitória que sobreviveu a todas as tentativas."""


@dataclass(slots=True)
class WeightGuard:
    """Acompanha o peso da janela de 1 minuto e pausa só o que resta dela."""

    used: int = 0
    ceiling: int = WEIGHT_CEILING
    _window_start: float = field(default_factory=time.monotonic)

    def observe(self, headers: httpx2.Headers) -> None:
        raw = headers.get("x-mbx-used-weight-1m")
        if raw is None or not raw.isdigit():
            return
        value = int(raw)
        # Contador caindo significa janela nova, não peso liberado na atual.
        if value < self.used:
            self._window_start = time.monotonic()
        self.used = value

    async def wait_if_needed(self) -> None:
        if self.used < self.ceiling:
            return
        remaining = WINDOW_SECONDS - (time.monotonic() - self._window_start)
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._window_start = time.monotonic()
        self.used = 0


class BinanceClient:
    """Busca klines com paginação. Instancie via ``async with``."""

    def __init__(
        self,
        client: httpx2.AsyncClient | None = None,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 4,
        weight_ceiling: int = WEIGHT_CEILING,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx2.AsyncClient(timeout=timeout)
        self._guard = WeightGuard(ceiling=weight_ceiling)
        self._max_retries = max_retries

    @property
    def used_weight(self) -> int:
        """Peso consumido na janela atual, conforme reportado pela Binance."""
        return self._guard.used

    async def __aenter__(self) -> BinanceClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _backoff(self, attempt: int) -> float:
        """1s na primeira falha, dobrando a cada tentativa seguinte."""
        return 2.0**attempt

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        """GET com retry em falha transitória. Só levanta ``BinanceError``."""
        last: Exception | None = None

        for attempt in range(self._max_retries):
            await self._guard.wait_if_needed()
            try:
                response = await self._client.get(f"{self._base_url}{path}", params=params)
            except httpx2.HTTPError as exc:
                last = BinanceUnavailableError(f"falha de transporte em {path}: {exc}")
                await asyncio.sleep(self._backoff(attempt))
                continue

            self._guard.observe(response.headers)

            if response.status_code in RETRYABLE_STATUS:
                last = BinanceUnavailableError(f"HTTP {response.status_code} em {path}")
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after else self._backoff(attempt)
                await asyncio.sleep(delay)
                continue

            if response.status_code == 400:
                body = response.json()
                if isinstance(body, dict) and body.get("code") == -1121:
                    raise SymbolNotListedError(str(params.get("symbol")))
                raise BinanceError(f"400 da Binance: {body}")

            if response.status_code >= 400:
                raise BinanceError(f"HTTP {response.status_code} em {path}")

            try:
                return response.json()
            except ValueError as exc:
                raise BinanceError(f"resposta não-JSON em {path}") from exc

        raise BinanceUnavailableError(
            f"{self._max_retries} tentativas esgotadas em {path}"
        ) from last

    def iter_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> AsyncIterator[list[Kline]]:
        """Gera candles página a página, sem materializar o intervalo inteiro.

        Valida o intervalo na chamada, não na primeira iteração — o erro
        aparece onde foi cometido.
        """
        if interval not in INTERVAL_MS:
            raise ValueError(f"intervalo não suportado: {interval}")
        return self._iter_pages(symbol, interval, start_ms, end_ms)

    async def _iter_pages(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None,
    ) -> AsyncIterator[list[Kline]]:
        step = INTERVAL_MS[interval]  # type: ignore[index]
        cursor = start_ms

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
                return

            yield [_to_kline(symbol, interval, row) for row in batch]

            if len(batch) < MAX_LIMIT:
                return
            cursor = int(batch[-1][0]) + step
            if end_ms is not None and cursor > end_ms:
                return

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> list[Kline]:
        """Coleta tudo em memória. Use ``iter_klines`` para intervalos longos."""
        out: list[Kline] = []
        async for page in self.iter_klines(symbol, interval, start_ms, end_ms):
            out.extend(page)
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
