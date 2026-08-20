"""Fixtures de dados compartilhadas pelos testes."""

from __future__ import annotations

from typing import Any

DAY_MS = 86_400_000
T0 = 1_704_067_200_000


def raw_kline(open_time: int, close: float = 100.0) -> list[Any]:
    """Formato posicional cru da Binance."""
    return [
        open_time,
        f"{close:.8f}",
        f"{close * 1.02:.8f}",
        f"{close * 0.98:.8f}",
        f"{close:.8f}",
        "1234.50000000",
        open_time + DAY_MS - 1,
        "1000000.00000000",
        4321,
        "600.00000000",
        "500000.00000000",
        "0",
    ]
