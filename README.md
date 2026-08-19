# infcap

Serviço HTTP que coleta, normaliza e serve dados históricos de candles (OHLCV) de exchanges de
cripto — hoje **Binance** e **Hyperliquid**. Mantém um cache local em SQLite com chave
`(symbol, interval, open_time)`, faz fetch incremental a partir do último candle conhecido e guarda
por ativo o rastro de frescor: quando foi buscado pela última vez, se o par ainda está listado e qual
foi o último erro.

O problema que resolve é o de quem precisa de série histórica confiável para análise: bater na API da
exchange a cada execução é lento, sujeito a rate limit e silenciosamente incompleto quando um par é
deslistado. O infcap coloca uma camada durável e idempotente na frente disso — reprocessar duas vezes
dá o mesmo resultado, e a ausência de dado é sempre distinguível de dado que nunca foi buscado.

Python 3.12+.

> **Nota:** este parágrafo foi derivado do código, não de um documento de produto. Se o posicionamento
> for outro, é aqui que se corrige.

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
├── api/
│   ├── health.py    # liveness e readiness
│   └── routes.py    # rotas de domínio (placeholder)
├── storage/
│   ├── schema.py    # DDL do cache SQLite (epoch ms UTC)
│   └── db.py        # leitura/escrita de klines e metadata
└── data/            # coletores por exchange (em construção)
tests/
```

## Licença

MIT — veja [LICENSE](LICENSE).
