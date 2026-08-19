"""Entrypoint: ``python -m infcap`` ou o script ``infcap``."""

import uvicorn

from infcap.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "infcap.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=not settings.is_production,
        log_config=None,  # o logging JSON próprio já está instalado
    )


if __name__ == "__main__":
    main()
