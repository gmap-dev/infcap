"""Rotas de domínio do infcap.

TODO: substituir o placeholder pelos recursos reais assim que o domínio for definido.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["infcap"])


class ServiceInfo(BaseModel):
    name: str
    description: str


@router.get("/", response_model=ServiceInfo)
async def root() -> ServiceInfo:
    return ServiceInfo(name="infcap", description="TODO: descrever o domínio")
