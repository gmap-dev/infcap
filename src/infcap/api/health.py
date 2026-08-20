"""Endpoints de health check, separados por semântica de orquestrador.

``/health/live``  — o processo está de pé (reiniciar se falhar).
``/health/ready`` — o processo aceita tráfego (tirar do balanceador se falhar).

Dependências externas entram só em readiness: um cache indisponível deve tirar a
instância do balanceador, nunca virar loop de reinício do container.
"""

import logging

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from infcap import __version__

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    status: str
    version: str
    checks: dict[str, bool] = {}


@router.get("/live", response_model=HealthStatus)
async def liveness() -> HealthStatus:
    return HealthStatus(status="ok", version=__version__)


async def _database_ok(request: Request) -> bool:
    """Toca o cache de verdade — presença de atributo não prova conexão viva."""
    conn = getattr(request.app.state, "db", None)
    if conn is None:
        return False
    try:
        async with conn.execute("SELECT 1") as cur:
            await cur.fetchone()
    except Exception:
        logger.exception("readiness: cache indisponível")
        return False
    return True


@router.get("/ready", response_model=HealthStatus)
async def readiness(request: Request, response: Response) -> HealthStatus:
    checks = {"database": await _database_ok(request)}

    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="degraded", version=__version__, checks=checks)

    return HealthStatus(status="ok", version=__version__, checks=checks)
