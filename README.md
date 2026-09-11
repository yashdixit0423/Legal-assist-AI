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

Stages 0 to 4 of ten are complete. See [docs/BUILD-LOG.md](docs/BUILD-LOG.md)
for the running record and what each stage delivered.

| Capability | State |
|---|---|
| Config, structured logging, typed errors | working |
| `GET /v1/health` — version, DB connectivity, corpus counts | working |
| `GET /metrics` — Prometheus | working |
| `legaledge-kb version` / `check-config` | working |
| Citation-correct section ordering (`section_no_sort`) | working |
| Database schema and migrations (10 tables, pgvector, HNSW + GIN) | working |
| Corpus fetch and parse — six Acts from the India Code API | working |
| Cross-links, chunking, embeddings, HNSW (`legaledge-kb index`) | working |
| `POST /v1/ask` — hybrid + RRF + rerank + abstention + citation validation | working |
| Corpus read API and `POST /v1/search` | Stage 5 |
| SSE streaming, query rewriting, `ask_logs` | Stage 6 |
| Auth and the BYOK credential vault | Stage 7 |

## Bring the stack up

Requires Docker with Compose v2.

```bash
cp .env.example .env
# Generate the two required secrets and paste them into .env:
#   openssl rand -hex 32                                        -> JWT_SECRET
#   python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
#                                                               -> CREDENTIAL_ENC_KEY
docker compose up -d --build
docker compose exec api alembic upgrade head
curl -s localhost:8000/v1/health | python3 -m json.tool
```

A healthy, migrated deployment answers `200` with `"status": "ok"`,
`"schema_ready": true` and zero corpus counts (nothing is ingested until Stage 2).
Before the migration runs, `"schema_ready"` is `false` — that is how you tell an
un-migrated stack from a broken one. If PostgreSQL
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

## Migrations

```bash
alembic upgrade head          # apply
alembic downgrade base        # roll back (drops every table and the extension)
alembic current               # show the applied revision
alembic revision --autogenerate -m "what changed"
```

The URL comes from `DATABASE_URL` via `Settings`, not from `alembic.ini`. Head is
`0001`. Section ordering is by `section_no_sort`, never by `section_no` — see
[docs/adr/0003](docs/adr/0003-identifiers-and-citation-ordering.md).

## Run the CLI

```bash
legaledge-kb --help
legaledge-kb version
legaledge-kb check-config     # validates the environment; secrets are never printed
```

```bash
# The corpus pipeline, in order. Each step is idempotent and resumable.
legaledge-kb fetch            # archive the six Acts from India Code, with checksums
legaledge-kb parse            # verify continuity, then write statute_sections
legaledge-kb index            # cross-links, chunks, embeddings, HNSW -- then stats
```

Remaining pipeline verbs (`explain`, `verify`) are registered by the stage that
implements them, so `--help` never advertises a command that does nothing.

## Ask a question

`POST /v1/ask` is the only endpoint that needs a model key. Set `LLM_API_KEY` in
`.env` (`LLM_MODEL` defaults to `anthropic/claude-sonnet-4-5`); without it the
endpoint returns a typed `402 missing_provider_key` rather than a generic
failure.

```bash
curl -s localhost:8000/v1/ask -H 'content-type: application/json' \
  -d '{"question":"When must a lease of immoveable property be registered?"}' | jq
```

Two things are worth understanding about the response:

- **`abstained: true` with HTTP 200 is a success.** It means nothing cleared the
  reranker score floor, so no model was called and nothing was invented. An
  out-of-corpus question costs nothing and needs no API key.
- **Every assertion carries a `[S<section_id>]` citation**, and the ids are
  checked in code against exactly the sections that were packed into the prompt.
  An answer citing anything else is regenerated once and then abstained on. That
  check — not the prompt instruction asking for it — is what makes the grounding
  claim testable.

## Run the tests

```bash
ruff check . && ruff format --check .
mypy
pytest -q
```

Database-backed tests create a uniquely named throwaway database, migrate it with
the real Alembic migration (not `create_all`), and drop it afterwards — so the
suite is repeatable and never inherits its own leftovers. They skip themselves
when `DATABASE_URL` is unreachable; CI always provides one, so nothing is
silently unverified there.

On a machine whose 5432 is already taken, run the stack on another port and point
the tests at it:

```bash
POSTGRES_PORT=5433 docker compose up -d
DATABASE_URL=postgresql://legaledge:legaledge@localhost:5433/legaledge pytest -q
```

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
