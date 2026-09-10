# LegalEdge — Phase 1.1 · Knowledge Base & Grounded Q&A

Backend for a legal knowledge base over Indian central statutes, with a grounded
retrieval-augmented question answering API.

A user asks a question in English or Hindi; the answer is assembled **only** from
statutory text the system actually retrieved, with a citation to every section it
relied on — and an honest refusal when the corpus does not cover the question.

> **Scope.** This repository is the backend only: FastAPI service plus the
> `legaledge-kb` corpus CLI. There is no frontend, no document upload, no document
> generation, no chat history, and no task queue. See
> [docs/adr/0002](docs/adr/0002-backend-only-scope.md).

## What works so far

Stage 0 of ten is complete. See [docs/BUILD-LOG.md](docs/BUILD-LOG.md) for the
running record and what each stage delivered.

| Capability | State |
|---|---|
| Config, structured logging, typed errors | working |
| `GET /v1/health` — version, DB connectivity, corpus counts | working |
| `GET /metrics` — Prometheus | working |
| `legaledge-kb version` / `check-config` | working |
| Database schema and migrations | Stage 1 |
| Corpus fetch / parse / index | Stages 2–4 |
| Corpus read API, auth, retrieval, `POST /v1/ask` | Stages 5–8 |

## Bring the stack up

Requires Docker with Compose v2.

```bash
cp .env.example .env
# Generate the two required secrets and paste them into .env:
#   openssl rand -hex 32                                        -> JWT_SECRET
#   python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
#                                                               -> CREDENTIAL_ENC_KEY
docker compose up -d --build
curl -s localhost:8000/v1/health | python3 -m json.tool
```

A healthy, empty deployment answers `200` with `"status": "ok"`,
`"schema_ready": false` (no migrations yet) and zero corpus counts. If PostgreSQL
is unreachable the endpoint answers `503` with `"status": "degraded"` — a deploy
probe must never read a broken dependency as healthy.

Services: `postgres` (pgvector/pgvector:pg16) and `api`. Redis is optional and
sits behind a profile:

```bash
docker compose --profile cache up -d
```

Optional Langfuse overlay:

```bash
docker compose -f compose.yml -f compose.observability.yml up -d
```

Production, with Caddy terminating TLS automatically:

```bash
LEGALEDGE_DOMAIN=kb.example.com LEGALEDGE_TLS_EMAIL=ops@example.com \
  docker compose -f compose.yml -f compose.prod.yml up -d
```

## Local development

Python 3.12 exactly. `uv` is not required.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements/api.txt -r requirements/dev.txt
pip install --no-deps -e .          # makes `app` and `legaledge_kb` importable

# The corpus pipeline's heavy extras (docling, ocrmypdf, datasets) are separate:
pip install -r requirements/corpus.txt

uvicorn app.main:app --reload        # needs a reachable DATABASE_URL
```

System packages the corpus pipeline needs outside Docker (already installed in the
image): `tesseract-ocr`, `tesseract-ocr-hin`, `ghostscript`, `qpdf`,
`poppler-utils`, `libpq5`.

`pyproject.toml` is the single source of truth for versions; `requirements/*.txt`
is generated from it. After changing a dependency:

```bash
python scripts/sync_requirements.py
```

## Run the CLI

```bash
legaledge-kb --help
legaledge-kb version
legaledge-kb check-config     # validates the environment; secrets are never printed
```

Pipeline verbs (`fetch`, `parse`, `chunk`, `embed`, `explain`, `verify`, `stats`)
are registered by the stage that implements them, so `--help` never advertises a
command that does nothing.

## Run the tests

```bash
ruff check . && ruff format --check .
mypy
pytest -q
```

Tests that need PostgreSQL skip themselves when `DATABASE_URL` is unreachable;
CI always provides one, so nothing is silently unverified there.

## Retrieval models

| Role | Model | Dimensions |
|---|---|---|
| Dense retriever | `NyayaLabs98/nyaya-embed-v1` | 768 |
| Cross-encoder reranker | `BAAI/bge-reranker-v2-m3` | — |

Both are loaded at a pinned commit revision, never at a floating `main`. The
embedding model has a hard 512-token ceiling, so chunks are capped at
`MAX_CHUNK_TOKENS=450` including the `passage:` prefix, and long sections split on
sub-section boundaries. Rationale and the models we rejected:
[docs/adr/0001](docs/adr/0001-retrieval-model-selection.md).

## Legal note

The corpus is built only from Government of India sources (India Code, the
Legislative Department, e-Gazette, ministry portals). Bare statutory text carries
no copyright in India under section 52(1)(q) of the Copyright Act; commercial
publishers' headnotes and annotations are never ingested. Every document records
its source URL, portal and SHA-256, and every section carries an as-of date. The
corpus is not a complete or current statement of the law.
