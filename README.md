# infcap

Serviço HTTP que coleta, normaliza e serve dados históricos de candles (OHLCV) de exchanges de
cripto — hoje **Binance** (spot); Hyperliquid está previsto e ainda não implementado. Mantém um
cache local em SQLite com chave `(symbol, interval, open_time)`, faz fetch incremental a partir do
último candle conhecido e guarda por ativo o rastro de frescor: quando foi buscado pela última vez,
se o par ainda está listado e qual foi o último erro.

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
| `INFCAP_DATABASE_PATH` | `infcap.db` | Arquivo do cache SQLite |
| `INFCAP_BINANCE_BASE_URL` | `https://api.binance.com` | Base da API da Binance |
| `INFCAP_REQUEST_TIMEOUT` | `10.0` | Timeout por request à exchange, em segundos |

## Health checks

| Rota | Significado | Uso no orquestrador |
|---|---|---|
| `/health/live` | O processo está de pé | Reiniciar o container se falhar |
| `/health/ready` | O processo aceita tráfego | Tirar do balanceador se falhar |

`readiness` toca o cache SQLite de verdade (`SELECT 1`) e responde `503` com
`checks: {"database": false}` se ele não responder. Dependências externas ficam só aqui, nunca em
`liveness` — caso contrário uma indisponibilidade do banco vira um loop de reinício do serviço.

## API

### `GET /v1/klines`

Serve a janela pedida a partir do cache, completando na exchange só o trecho ausente.

| Parâmetro | Obrigatório | Descrição |
|---|---|---|
| `symbol` | sim | Par em maiúsculas, ex. `BTCUSDT` |
| `interval` | sim | `1m`, `5m`, `15m`, `1h`, `4h` ou `1d` |
| `start` | sim | Início da janela, epoch ms UTC |
| `end` | não | Fim da janela, epoch ms UTC |
| `refresh` | não | `false` responde só o que já está em disco (padrão `true`) |

```bash
curl "http://127.0.0.1:8000/v1/klines?symbol=BTCUSDT&interval=1d&start=1704067200000"
```

A resposta traz `count` (candles na janela) e `fetched` (quantas vieram da exchange nesta chamada) —
com o cache quente, `fetched` é `0` e nenhum request sai.

| Situação | Status |
|---|---|
| Par ausente do spot da Binance | `404` |
| Binance indisponível após os retries | `503` |
| Requisição rejeitada pela Binance | `502` |
| Parâmetro inválido | `422` |

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
│   ├── deps.py      # recursos do lifespan expostos às rotas
│   ├── health.py    # liveness e readiness
│   └── routes.py    # GET /v1/klines
├── storage/
│   ├── schema.py    # DDL do cache SQLite (epoch ms UTC)
│   └── db.py        # leitura/escrita de klines e metadata
└── data/
    ├── binance.py   # cliente HTTP da Binance (spot, klines)
    └── collector.py # coleta incremental: exchange -> cache
tests/
```

## Licença

MIT — veja [LICENSE](LICENSE).
