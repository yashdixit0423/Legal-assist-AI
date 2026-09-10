# LegalEdge Phase 1.1 — build log

The durable memory of this build. One dated section per stage: what was built,
what was decided, where we deviated from the plan, what is knowingly missing, and
what the next stage needs. This file plus
`LegalEdge-Phase1.1-Knowledge-Base-and-RAG.docx` should be enough for a session
with no other context to continue the work.

Ten stages, built one at a time, each on its own branch, each ending green.

| Stage | Name | State |
|---|---|---|
| 0 | Scaffold and environment | complete |
| 1 | Data model and migrations | complete |
| 2 | Corpus acquisition, nyaya-statute-db decision | not started |
| 3 | Parser, structuring, golden fixtures | not started |
| 4 | Index — cross-links, chunking, embeddings | not started |
| 5 | Corpus read API | not started |
| 6 | Auth and the BYOK gateway | not started |
| 7 | Retrieval pipeline | not started |
| 8 | Answer pipeline | not started |
| 9 | Explanations, evaluation, hardening, deploy | not started |

---

## 2026-09-10 · Stage 0 — Scaffold and environment

Branch `stage-0-scaffold`. The repository started empty; nothing was inherited or
migrated. (A neighbouring folder, `~/Desktop/LegalEdge-AI-Project-main`, holds an
unrelated June 2025 Flask/Ollama prototype. It shares no architecture with this
plan and was deliberately left untouched.)

### Built

- **Repository layout** per spec §12, minus everything the scope fences exclude
  (see ADR 0002). `tests/unit/test_repo_layout.py` asserts the required
  directories exist *and* that the out-of-scope ones do not, so a later session
  cannot quietly start an `apps/web/`.
- **Dependencies.** `pyproject.toml` is the single source of truth, every direct
  dependency pinned to an exact version (no wildcards — a test enforces this).
  Four groups: default (API + CLI), `corpus`, `dev`, `eval`. `requirements/*.txt`
  is generated from it by `scripts/sync_requirements.py`, and
  `tests/unit/test_requirements_sync.py` fails if the two drift.
- **Dockerfile**, multi-stage: a builder that compiles into `/opt/venv`, and a
  runtime with no compilers, running as non-root `legaledge` (uid 1001). System
  packages: `tesseract-ocr`, `tesseract-ocr-hin`, `ghostscript`, `qpdf`,
  `poppler-utils`, `libpq5`. `HEALTHCHECK` hits `/v1/health`.
- **Compose.** `compose.yml` = `postgres` (pgvector/pgvector:pg16, volume,
  healthcheck) + `api`, with `redis` behind a `cache` profile.
  `compose.prod.yml` adds Caddy and unpublishes the API and database ports.
  `compose.observability.yml` is the optional Langfuse overlay. Model weights live
  in a named volume (`model-cache` → `/models`, `HF_HOME`) so containers do not
  re-download on restart.
- **Settings** (`app/core/config.py`): one pydantic-settings object, every value
  from the environment, required values with no default so startup fails loudly
  and legibly. `CREDENTIAL_ENC_KEY` is validated as 32 base64 bytes at load time,
  not at first use. `FETCH_USER_AGENT` must carry a contact address.
  `MAX_CHUNK_TOKENS` is validated against the embedding model's 512-token ceiling.
- **structlog**: JSON in deployment, console locally, with a redaction processor
  that blanks secret-shaped keys and *drops* keys that can carry user text or a
  full prompt (`question`, `prompt`, `messages`, `answer`, `turns`).
- **Exception hierarchy** (`app/core/errors.py`) mapped to HTTP in exactly one
  place (`app/core/error_handlers.py`), with a uniform
  `{"error": {code, message, details?, request_id}}` envelope.
  `missing_provider_key` is a distinct 402 so a frontend can route to Settings.
- **`GET /v1/health`**: app version, database connectivity and latency, whether
  the schema exists yet, and corpus counts. 200 when healthy, 503 + `degraded`
  when the database is unreachable. `GET /metrics` via
  prometheus-fastapi-instrumentator.
- **`legaledge-kb` CLI** with `version` and `check-config`. Pipeline verbs are
  *not* registered until the stage that implements them, and a test asserts they
  are absent — `--help` never advertises a command that does nothing.
- **CI** (`.github/workflows/ci.yml`): requirements-sync check, `ruff check`,
  `ruff format --check`, `mypy`, `pytest` against a pgvector service container,
  plus a separate job that builds the image.
- **Docs**: this log, ADR 0001 (retrieval models), ADR 0002 (backend-only scope),
  README.

### Decisions

1. **ADR 0001 — retrieval models.** `NyayaLabs98/nyaya-embed-v1` (768 dims) for
   dense retrieval, not BGE-M3 (1024); `BAAI/bge-reranker-v2-m3` for reranking,
   swappable by config; `law-ai/InLegalBERT` excluded from the retrieval path;
   every model loaded at a pinned revision SHA. The e5 `passage:`/`query:`
   prefixes and the 512-token ceiling are encoded as constants in
   `app/core/config.py` and asserted by tests.
2. **ADR 0002 — backend only.** No frontend, no upload, no generation, no chat
   persistence, no queue, no object storage, no Kubernetes.
3. **Dependency groups, not one flat set.** `docling` + `ocrmypdf` + `datasets`
   (~1.5 GB) are `corpus` extras, installed into the image only when
   `INSTALL_CORPUS=true`. The request path never imports them.
4. **`sqlalchemy[asyncio]`, not bare `sqlalchemy`.** Found by a failing test: the
   async engine needs `greenlet`, which only arrives via that extra. Without it
   the API imports fine and fails on the first database call.
5. **Local Postgres port.** The developer machine already had something on 5432,
   so local runs use `POSTGRES_PORT=5433`. `.env.example` keeps 5432; CI uses 5432.

### Deviations from the plan

| Plan says | We did | Why |
|---|---|---|
| BGE-M3, `vector(1024)` | nyaya-embed-v1, `vector(768)` | ADR 0001, per instruction |
| Compose services `web, api, postgres, caddy` | `postgres, api` (+ optional `redis`, `langfuse`); Caddy in the prod overlay | No frontend in this repository (ADR 0002) |
| `uv` for dependency management | pip + generated `requirements/*.txt` | `uv` is not installed on this machine; pyproject stays the source of truth |
| PEP 735 `[dependency-groups]` | `[project.optional-dependencies]` | Local pip is 24.2; PEP 735 needs pip ≥ 25.1 |
| `langfuse==2.5*.*` | `langfuse==2.59.7` | Highest release inside the requested series |
| `litellm==1.5*.*` | `litellm==1.59.12` | Same |

### Bugs found and fixed inside this stage

Recorded because each was invisible to source inspection and only surfaced when
something real ran:

1. **`greenlet` missing.** SQLAlchemy's async engine needs it; it is not a
   dependency of bare `sqlalchemy`. Surfaced only when a test opened a real
   connection. Fixed by pinning `sqlalchemy[asyncio]==2.0.36`.
2. **Loggers created at import time escaped the redaction processor.**
   `get_logger()` used `structlog.get_logger().bind(...)`, and `.bind()`
   materialises the proxy against whatever configuration is installed *at that
   moment* — which, for a module-level logger, is structlog's console default.
   Every module logger would have logged unredacted secrets for the life of the
   process. The container's non-JSON log lines were the only visible symptom.
   Fixed by passing the name as an initial value (`logger_name`, renamed to
   `logger` by a processor, because `logger` is a reserved kwarg) so the proxy
   resolves lazily. Regression test:
   `test_logger_created_before_configuration_still_redacts`.
3. **`/v1/health` returned 500 when the database was unreachable.** Not every
   driver failure is a `SQLAlchemyError` — asyncpg raises
   `InvalidAuthorizationSpecificationError` straight through on connect. A health
   probe must report `degraded`, never crash. Fixed with a deliberately broad
   catch that reports the exception *class* in the response, so a bug in our own
   SQL still shows up by name. Test:
   `test_driver_level_failure_is_degraded_not_a_500`.

### Known gaps at the end of Stage 0

- **No Alembic environment yet** (`apps/api/alembic/` is an empty tree). Stage 1
  owns `alembic.ini`, `env.py` and the first migration. `schema_ready` on
  `/health` is therefore `false`, and the corpus counts are structurally zero.
- **`EMBED_MODEL_REVISION` and `RERANK_MODEL_REVISION` ship empty.** The real SHAs
  cannot be resolved without downloading the model repositories, which Stage 4
  does. An empty revision must fail loudly at model-load time rather than
  silently resolving to `main`. No placeholder SHA was invented.
- **No lockfile.** Direct dependencies are pinned exactly; transitive ones are
  not. If reproducibility becomes a requirement, `uv lock` or `pip-compile` is the
  answer — ask before adding either.
- **`content/corpus/manifest.yaml` does not exist** (Stage 2). Note that PyYAML is
  *not* in the approved dependency list but the manifest is specified as YAML —
  flagged for decision.
- **Rate limiting is not implemented** (Stage 9 per the plan). No rate-limiting
  library was added.

### What Stage 1 needs

- An Alembic environment reading `Settings.database_url_sync` (psycopg), with
  `CREATE EXTENSION IF NOT EXISTS vector` in the first migration.
- Nine tables per spec §06 plus `users` and `api_credentials`.
- `embedding vector(768)` — see `EMBEDDING_DIM` in `app/core/config.py`. Getting
  this wrong means re-embedding the whole corpus later.
- HNSW on `kb_chunks.embedding` (cosine, `m=16`, `ef_construction=64`), GIN on
  `kb_chunks.tsv`, btree on `(statute_id, section_no_sort)`.
- `section_no_sort` must order legal citations correctly: 9 before 10, and 2A, 14B
  and 21-A in their right places. Tests for that ordering specifically.
- Once the models exist, move `app/services/corpus_stats.py` off its lightweight
  `sqlalchemy.table()` constructs and onto the ORM models.

---

## 2026-09-10 · Stage 1 — Data model and migrations

Branch `stage-1-schema`. Migration head `0001`.

### Built

- **Ten tables** as SQLAlchemy 2.0 declarative models, split across
  `app/db/models/` per spec §12: `statute.py` (statutes, statute_parts,
  statute_sections, section_explanations), `kb_chunk.py` (kb_chunks,
  statute_links), `ask_log.py` (ingest_runs, ask_logs), `user.py` (users,
  api_credentials).
  Note on the count: the brief says "nine tables", and spec §06 has nine rows —
  but its last row is `users · api_credentials`, two tables. Eight corpus tables
  plus those two is ten.
- **One migration, `0001_initial_schema`**, hand-finished from an autogenerate
  baseline. Creates the `vector` extension first, then every table, then the
  three indexes that carry the load:
  - `ix_kb_chunks_embedding_hnsw` — HNSW, `vector_cosine_ops`, `m=16`,
    `ef_construction=64`;
  - `ix_kb_chunks_tsv_gin` — GIN on the tsvector column;
  - `ix_statute_sections_citation_order` — btree on
    `(statute_id, section_no_sort)`.
  `embedding` is `vector(768)`. The dimension is written out in the migration
  rather than imported from `app.core.config`, so the migration stays a frozen
  snapshot.
- **`section_no_sort`** (`app/services/kb/section_numbers.py`) — the citation
  ordering key. Format, rationale and the deliberate trade-offs are in ADR 0003.
- **`ask_logs` is anonymous by construction**: no `user_id`, no foreign keys at
  all, asserted by a test so the column cannot reappear.
- **Alembic environment** at `alembic.ini` + `apps/api/alembic/env.py`, reading
  the psycopg URL from `Settings` unless a URL is supplied explicitly (which is
  how the tests point migrations at a throwaway database).
- **`corpus_stats` moved onto the ORM models**, so `/v1/health` now reports the
  real `schema_ready` flag and real counts.

### Decisions

1. **ADR 0003** — `BIGINT` identities for corpus rows (citation ids go into the
   prompt, where a UUID costs ~13 tokens per block for nothing) and `UUID` for
   accounts; the sort-key format; `VARCHAR` + `CHECK` instead of native
   PostgreSQL enums.
2. **`COLLATE "C"` on `section_no_sort`.** Measured, not assumed: on this
   `en_US.utf8` server the locale ordering agrees with the byte ordering for our
   key format, so this is determinism against a differently-initialised server
   (notably ICU), not a fix for an observed break. The earlier draft of this
   file and of the model docstring claimed the locale collation breaks the
   ordering; that claim was wrong and has been corrected.
3. **Overflow raises rather than truncates** in the sort key. A truncated key
   points a citation at the wrong provision; a failed ingest does not.
4. **Special indexes are declared on the models as well as in the migration**, so
   `compare_metadata` has something to compare against and the drift test needs no
   exception list.

### Deviations from the plan

| Plan says | We did | Why |
|---|---|---|
| `embedding vector(1024)` | `vector(768)` | ADR 0001 |
| "nine tables" | ten | §06's last row names two tables |
| `statute_links` keyed by (from, to, relation) | `id` PK **plus** a unique constraint on (from, to, relation) | Lets the extractor upsert idempotently while still carrying `raw_text` |
| `section_explanations` keyed by `section_id` | `id` PK plus unique (section_id, lang, prompt_version) | Prompt-versioned regeneration needs more than one row per section |

### Bugs found and fixed inside this stage

1. **`alembic.ini` was never copied into the Docker image.** `alembic upgrade
   head` worked on the host and failed in the container with "No config file
   'alembic.ini' found" — i.e. the deployed stack could not be migrated at all.
   Found by running the command inside the container rather than trusting the
   host run. Guard added:
   `tests/unit/test_repo_layout.py::test_dockerfile_ships_everything_the_migrations_need`.
2. **The Alembic script template dropped `${imports}`**, so the autogenerated
   migration referenced `pgvector.sqlalchemy.vector.VECTOR` and
   `postgresql.ARRAY` without importing either. It would have failed on first
   import. Template fixed and the imports added.
3. **The model/migration drift test had an escape hatch.** Its first version
   filtered out diffs mentioning "hnsw", which also hid the GIN index. Declaring
   both indexes on the model removed the need for any filter, and the assertion
   is now `diff == []`.

### Known gaps at the end of Stage 1

- **`tsv` is a plain nullable column, not a generated one.** Spec §04 wants
  English *and* Hindi text-search configurations, and PostgreSQL 16 ships no
  `hindi` configuration — only `simple` would work for Devanagari without a
  dictionary. Stage 4 has to decide: `simple` for Hindi, a custom configuration,
  or a second column. Flagged rather than guessed.
- **No data yet.** Every table is empty; Stage 2 fetches and Stage 3 parses.
- **`section_count` on `statutes` is a stored counter with nothing maintaining
  it.** Stage 3 must set it, or it will read 0 forever.
- **`Provider` enum has no CHECK constraint** on `api_credentials.provider`,
  unlike the other four vocabularies: the provider catalogue is Stage 6's and
  will grow, so constraining it now would mean a migration per provider.
- Local runs need `DATABASE_URL=...localhost:5433/...` because this machine's
  5432 is occupied; CI uses 5432.

### What Stage 2 needs

- The manifest at `content/corpus/manifest.yaml` (Acts per tier with source
  URLs). PyYAML is still not in the approved dependency list — decision pending.
- `ingest_runs` is ready to be written by the fetcher: `status` is one of
  running / succeeded / partial / failed, and `warnings` / `errors` are JSONB
  arrays for the per-run report.
- `statutes.source_sha256` is a `char_length = 64` CHECK, so the fetcher must
  store a hex digest, not base64.
- Evaluate `NyayaLabs98/nyaya-statute-db` **before** writing a parser, and stop
  for a decision.
