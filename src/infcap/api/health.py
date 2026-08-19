"""Endpoints de health check, separados por semântica de orquestrador.

``/health/live``  — o processo está de pé (reiniciar se falhar).
``/health/ready`` — o processo aceita tráfego (tirar do balanceador se falhar).
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from infcap import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthStatus(BaseModel):
    status: str
    version: str


@router.get("/live", response_model=HealthStatus)
async def liveness() -> HealthStatus:
    return HealthStatus(status="ok", version=__version__)


@router.get("/ready", response_model=HealthStatus)
async def readiness(response: Response) -> HealthStatus:
    """Agregue aqui as checagens de dependências (banco, cache, filas).

    Enquanto a lista estiver vazia o serviço é sempre considerado pronto.
    """
    checks: dict[str, bool] = {}

    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="degraded", version=__version__)

    return HealthStatus(status="ok", version=__version__)
