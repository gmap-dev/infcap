# infcap

> **TODO:** descrever o que o infcap faz, para quem, e qual problema resolve.
> Este parágrafo é o primeiro contato de qualquer pessoa com o projeto — preencher antes do primeiro release.

Serviço HTTP em Python 3.12+.

## Requisitos

- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/) para dependências e ambiente virtual

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Como rodar

```bash
uv sync                      # cria .venv e instala tudo, inclusive dev
cp .env.example .env         # ajuste as variáveis conforme necessário
uv run infcap                # sobe em http://127.0.0.1:8000
```

Documentação interativa em `http://127.0.0.1:8000/docs` (desabilitada em produção).

## Desenvolvimento

```bash
uv run pytest                # testes
uv run pytest --cov          # testes com cobertura
uv run ruff check .          # lint
uv run ruff format .         # formatação
uv run mypy                  # tipagem estrita
```

Os quatro comandos acima são exatamente o que a CI executa — se passam local, passam no GitHub Actions.

## Configuração

Todas as variáveis usam o prefixo `INFCAP_` e são validadas na inicialização: um valor
inválido derruba o processo no boot, nunca em tempo de request.

| Variável | Padrão | Descrição |
|---|---|---|
| `INFCAP_ENVIRONMENT` | `local` | `local`, `staging` ou `production` |
| `INFCAP_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |
| `INFCAP_HOST` | `127.0.0.1` | Endereço de bind |
| `INFCAP_PORT` | `8000` | Porta de bind |

## Health checks

| Rota | Significado | Uso no orquestrador |
|---|---|---|
| `/health/live` | O processo está de pé | Reiniciar o container se falhar |
| `/health/ready` | O processo aceita tráfego | Tirar do balanceador se falhar |

Dependências externas (banco, cache, filas) devem ser agregadas em `readiness`, nunca em `liveness` —
caso contrário uma indisponibilidade do banco vira um loop de reinício do serviço.

## Docker

```bash
docker build -t infcap .
docker run --rm -p 8000:8000 --env-file .env infcap
```

Build multi-stage: as dependências ficam em uma camada própria e só são reconstruídas quando
`pyproject.toml` ou `uv.lock` mudam. O runtime roda como usuário sem privilégios (uid 10001).

## Estrutura

```
src/infcap/
├── __main__.py      # entrypoint (uvicorn)
├── app.py           # fábrica da aplicação
├── config.py        # settings validadas por ambiente
├── logging.py       # logging estruturado em JSON
└── api/
    ├── health.py    # liveness e readiness
    └── routes.py    # rotas de domínio (placeholder)
tests/
```

## Licença

MIT — veja [LICENSE](LICENSE).
