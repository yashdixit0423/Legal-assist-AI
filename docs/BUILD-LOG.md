# LegalEdge Phase 1.1 — build log

The durable memory of this build. One dated section per stage: what was built,
what was decided, where we deviated from the plan, what is knowingly missing, and
what the next stage needs. This file plus
`LegalEdge-Phase1.1-Knowledge-Base-and-RAG.docx` should be enough for a session
with no other context to continue the work.

Ten stages, built one at a time, each on its own branch, each ending green.

**Plan revised 2026-09-11** — resequenced to reach a working cited answer sooner.
Stage numbers below are the *new* ones; Stages 0 and 1 are unchanged and done.

| Stage | Name | State |
|---|---|---|
| 0 | Scaffold and environment | complete |
| 1 | Data model and migrations | complete |
| 2 | Corpus: evaluate nyaya-statute-db, then acquire + parse six Acts | in progress |
| 3 | Cross-links, chunking with the `passage:` prefix, embeddings, HNSW + GIN | not started |
| 4 | **Minimal `POST /v1/ask`** — hybrid + RRF + rerank + floor + abstention + generation + citation validator. Plain JSON, key from `.env`. **The milestone.** | not started |
| 5 | Corpus read API and search | not started |
| 6 | SSE streaming, query rewriting from request turns, `ask_logs` | not started |
| 7 | Auth and the BYOK credential vault | not started |
| 8 | Gold set, metrics, explanations job | not started |
| 9 | Hardening, Docker image, deploy, CI | not started |

### Scope cut — 2026-09-11

Directed by the project owner to move faster. Recorded here because a later
session will otherwise read the absences as oversights.

**Corpus is six Acts, not twenty:** Indian Contract Act 1872, Transfer of
Property Act 1882, Registration Act 1908, Indian Stamp Act 1899, Information
Technology Act 2000, DPDP Act 2023. One golden fixture (DPDP 2023), not two.

**Deferred to Stage 9:** Langfuse, Sentry, Prometheus, log-redaction polish, rate
limiting, ETags, response caching, Caddy, production compose, Docker image
builds. The code for the observability pieces is already in place from Stage 0
and simply is not being extended.

**Deferred entirely for now:** auth (no JWT, no login, no credential
encryption — one LLM API key is read from `.env`), Ragas, the explanations batch
job, and Hindi support. The `users` and `api_credentials` tables **stay in the
schema unchanged**, so Stage 7 is additive rather than a migration rewrite.

**Testing policy changed.** Full suites are now reserved for the four things that
can silently produce a wrong legal answer:

1. `section_no_sort` ordering
2. the chunker's `passage:` / `query:` prefixes
3. the abstention gate
4. the citation validator

Everything else gets one smoke test. `tests/test_smoke.py` replaced eleven files
(218 tests became 71). **Guards deliberately given up in that trade**, so nobody
mistakes their absence for a claim that they still hold: the no-`os.environ`
grep guard; the `.env.example` completeness check; the pyproject↔requirements
drift check; the repo-layout and out-of-scope-directory checks; the
Dockerfile-ships-`alembic.ini` check; the model↔migration drift check; the
per-error-class HTTP mapping matrix; and the eager-logger redaction regression
test from Stage 0. The redaction *behaviour* is still covered by one smoke test;
the initialisation-order regression is not.

**`mypy` is advisory, not a gate.** `ruff check` remains a gate. The CI workflow
is frozen as written and is no longer reported on.

**No further ADR files.** Decisions from here are dated paragraphs in this file.
ADRs 0001–0003 stand and are still referenced from the code.

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

---

## 2026-09-11 · Stage 2 (part 1) — the nyaya-statute-db evaluation

Branch `stage-2-corpus-eval`. No corpus code written yet: the plan requires this
evaluation and a decision first.

### What was evaluated

`NyayaLabs98/nyaya-statute-db`, revision `7e13be9e5f0a2c1532272fcadb6c51de992d4410`,
5,063 rows across 28 Act files plus a mappings table and a guidance file. Licence
declared as `other` / `gov-india-public-domain`, pointing at indiacode.gov.in.
Downloaded the three files that overlap our six-Act corpus (`contract_act_1872`,
`tpa_1882`, `it_act_2000`) and compared them against the official India Code text
of the Indian Contract Act, 1872.

### Coverage against our six Acts — 3 of 6

| Act | In dataset | Rows |
|---|---|---|
| Indian Contract Act, 1872 | yes | 192 |
| Transfer of Property Act, 1882 | yes | 135 |
| Information Technology Act, 2000 | yes | 122 |
| Registration Act, 1908 | **no** | — |
| Indian Stamp Act, 1899 | **no** | — |
| DPDP Act, 2023 | **no** | — |

The absent three include our golden-fixture Act. (`dpa_1961.jsonl` is the Dowry
Prohibition Act, not DPDP.)

### Section inventory — excellent

Contract Act: 192 rows, numeric gap exactly `76–123` and nothing after `238`,
which matches the Sale of Goods repeal of 1930 and the Partnership repeal of
1932 precisely; `19A` and `178A` both present. TPA: gaps at 74–75, 80, 85–90, 97,
99. IT Act: all 31 alpha-suffixed insertions from the 2008 amendment present
(3A, 43A, 66A–66F, 67A–67C, 69A/B, 72A, 79A, 84A–C). No duplicate section
numbers anywhere. Marginal notes (`title`) populated on 100% of rows. Sections
are stored whole, not pre-split, which suits our own chunker.

### Text fidelity — materially degraded against a clean available source

Measured across 360 KB of dataset text for the three Acts:

| Signal | Dataset | Official India Code text |
|---|---|---|
| Curly apostrophes `’` | **0** | 283 |
| Em dashes `—` | 35 (Contract) | 268 |
| `A's son` rendered as `As son` | 20 in Contract Act | 0 |
| Unbalanced `[` vs `]` amendment brackets | off by 2 / 30 / 17 | n/a |
| Amendment markers (`Ins. by`, `w.e.f.`) | 0 / 0 / 13 rows | present throughout |

Section 19A side by side: the official text reads `A’s son has forged B’s name`;
the dataset reads `As son has forged Bs name`. The typographic apostrophe was
deleted rather than converted, which corrupts words rather than merely
restyling them. Section 27 shows the same loss on side-headings —
`Exception 1.—Saving of…sold.—One who sells` becomes
`Exception 1 . Saving of…sold .One who sells`.

An early reading of this blamed the source: India Code's own
`preamble_footnote` metadata field does contain `Her Majestys`. That inference
was wrong, and the control disproves it — the Act **text** bitstream has 283
apostrophes and zero corrupted possessives. The damage is the dataset's.

In the dataset's favour: it removes the footnote text and page numbers that the
official extraction interleaves into the middle of section bodies. That is real
cleaning work — it just discards the amendment history instead of capturing it.

### Metadata our schema needs and the dataset does not carry

`amendment_note`, `footnotes`, `is_omitted`, per-section `commenced_on` (its
`effective_date` is the whole Act's commencement, identical on all 192 Contract
Act rows including sections inserted in 1899), `as_of_date`, `source_sha256`,
and the PART/CHAPTER hierarchy (`chapter` is null on 192/192 Contract Act and
135/135 TPA rows). Repealed sections are omitted rather than marked.

### The finding that decides it: India Code serves sections through an API

India Code has migrated to DSpace 7 with an Angular front end, so **the spec's
lxml/selectolax "section-wise HTML adapter" cannot work** — the pages are a
JavaScript shell. The REST API underneath, however, is better than the HTML ever
was. `GET /server/api/core/items/{uuid}` on a `collection: SECTION` item returns:

| India Code field | Our column |
|---|---|
| `dc.identifier.section_number` | `section_no` |
| `dc.title` | `marginal_note` |
| `dc.identifier.section_page_note` (HTML) | `text_verbatim` + `text_raw` |
| `dc.identifier.section_footnote` (HTML) | `footnotes`, `amendment_note` |
| `dc.identifier.order_number` | `order_idx` |
| `dc.identifier.repealed` | `is_omitted` |
| `act_name`, `act_number`, `act_year`, `enact_date`, `enforcement_date`, `ministry_name` | `statutes.*` |

Searching an Act's `act_id` enumerates its parts: 271 items for the Contract
Act, including `s.81 Repealed.` and `s.83 Repealed.` — the repeal markers the
dataset drops. All six of our Acts resolve, DPDP 2023 included
(handle `123456789/496508`). Both English and Hindi PDFs are attached per Act,
with DSpace's extracted text alongside.

Reachability, measured today: `indiacode.gov.in` answers (no `robots.txt` is
served at all); `www.indiacode.gov.in` presents a certificate that does not match
the hostname; `www.indiacode.nic.in` returns 403 from Akamai. So the fetcher must
target the apex `indiacode.gov.in` host, and treat the absent `robots.txt` as
permission-with-politeness rather than as an error.

### Recommendation

**Build our own from the India Code DSpace REST API. Do not import
nyaya-statute-db as corpus text.** It covers half our Acts, omits the fixture
Act, carries none of the amendment metadata the schema is built around, and its
text is character-level degraded against a source that is authoritative, richer
and reachable.

Because that source is structured per section, this is not the expensive option
the plan feared. Most of the "hierarchy parser" collapses into an HTML-fragment
cleaner plus a footnote extractor; there is no PDF path and no OCR on the primary
route.

**Keep the dataset as a test oracle.** Its section inventory is independently
correct for three of our Acts, which makes it a free cross-check for the
continuity guardrail — if our fetch of the Contract Act does not produce 190
in-force sections with `19A` and `178A` present and `76–123` absent, one of the
two is wrong and we look. That is the one use where its weaknesses do not matter.

### Decision pending

Recorded so the next session knows this was asked and not yet answered: whether
to proceed on that recommendation. Also still unanswered: PyYAML for the
manifest. To avoid blocking, the manifest will be written as **TOML** (stdlib
`tomllib`, no new dependency) unless directed otherwise — it stays a data file in
`content/corpus/`, so adding the seventh Act remains a data edit.

---

## 2026-09-11 · Stage 2 (part 2) — fetcher, India Code adapter, parser, fixture

Six Acts fetched, archived with checksums and parsed into the database: **778
section rows, 665 of them in force.** All six pass the guardrails.

### Built

- `content/corpus/manifest.toml` — six Acts, TOML so no dependency was added.
  Each entry pins India Code's `act_id`. **The `AC_CEN_` prefix is load-bearing:**
  searching by title returns state re-publications of these central Acts
  (Chhattisgarh, UP, Rajasthan and Delhi all host their own copies of the
  Contract Act), and ingesting one would put a state's text under a central
  citation. The central versions were found by scoping the search to the
  "Acts" collection `69a0c1fb-7b22-4481-b16a-1dc59b5d02e6`.
- `services/kb/fetch.py` — rate limit, exponential retry, contact-bearing
  User-Agent, SHA-256, archive under `CORPUS_ARCHIVE_DIR`, resume from archive.
- `services/kb/adapters/indiacode_api.py` — DSpace 7 REST adapter. Drops items
  whose `act_id` differs from the one requested: the search endpoint is
  full-text, so a neighbouring Act that merely mentions this one's identifier
  would otherwise be ingested under the wrong citation.
- `services/kb/parse.py` — HTML fragment to text using the standard library, no
  lxml. Footnote markers are kept inline as `[N]`; `text_raw` keeps the original
  fragment. `segment_section()` finds sub-section, proviso, Explanation and
  Illustration boundaries for the Stage 3 chunker.
- `services/kb/verify.py` — continuity, plausibility, duplicate and
  marginal-note-coverage checks; non-zero exit on failure.
- `services/kb/ingest.py` — fetch and parse orchestration, upserting by
  `(statute_id, section_no)` and writing `ingest_runs`.
- CLI: `fetch`, `parse`, `stats` (`--tier`, `--act`, `--refresh`, `--lenient`).
- `eval/fixtures/dpdp-act-2023.{payload,golden}.json` and
  `tests/unit/test_dpdp_fixture.py`.

### Decisions

**No lxml or selectolax on the primary path.** India Code's API returns short
HTML fragments, so `html.parser` is enough. The corpus extras stay uninstalled
for the API image and CI.

**`click==8.1.8` pinned.** Not a new dependency — a compatibility pin on an
existing transitive one. Click 8.2 changed `Parameter.make_metavar()`, which
typer 0.13 calls with the old signature, so `--help` crashed.

**The archive is the fetched JSON, not a PDF.** Provenance is the API payload's
SHA-256. The English and Hindi PDFs are attached per Act on the same API and were
deliberately not downloaded (Hindi is deferred).

**`commenced_on` is null for DPDP.** India Code's `enforcement_date` is empty for
that Act, which is correct — it commenced in phases by notification. Recorded as
null rather than invented.

**Verbatim text keeps the portal's own artefacts.** India Code's
`section_page_note` contains `---` where the printed Act has an em dash, and
straight quotes where it has curly ones. Restoring them would be editorialising
the one field the product displays as authoritative, so the source bytes are kept
as they are. Worth revisiting if the reader looks wrong.

### What the guardrails caught

Three real defects, all found by the continuity check rather than by reading code:

1. **Repealed sections counted as live.** India Code keeps repealed provisions as
   items so the numbering stays continuous. First detection attempt missed them
   and the Contract Act came out at 260 in-force against an oracle of 190.
2. **Two different repeal conventions.** The Contract Act writes the marginal
   note `Repealed.`; the Transfer of Property Act writes `[Repealed.].` and puts
   a footnote marker before the bracketed old note —
   `[1][Decree of foreclosure suit.] Rep. by the Code of Civil Procedure`. The
   detector handles both. After the fix, **Contract Act 192 and TPA 135, matching
   the independent nyaya-statute-db counts exactly.**
3. **My own manifest oracle was wrong** for the Contract Act (I wrote 190 from
   arithmetic; the dataset has 192, and India Code agrees with the dataset).

**Where the oracle is wrong and we are right:** the IT Act. The dataset's 122
rows count 14 provisions that India Code marks omitted — s.20, the Cyber
Appellate Tribunal sections 49–56, s.66A and ss.91–94 — and are missing s.61
("Civil court not to have jurisdiction"), which is live law. `expected_sections`
is therefore absent for that Act, with the reason in the manifest. Note that
India Code itself marks **s.66A as "Omitted."** following *Shreya Singhal*, even
though Parliament never repealed it; we follow the portal and keep the text.

### Corpus as parsed

| Act | rows | in force | warnings |
|---|---:|---:|---|
| Indian Contract Act, 1872 | 268 | 192 | none |
| Transfer of Property Act, 1882 | 148 | 135 | none |
| Registration Act, 1908 | 96 | 90 | 1 long section (s.89, 19.3k chars) |
| Indian Stamp Act, 1899 | 97 | 95 | 2 long sections (s.2 19.1k, s.47 29.1k) |
| Information Technology Act, 2000 | 125 | 109 | none |
| DPDP Act, 2023 | 44 | 44 | none |

The long-section warnings are genuine: those provisions are long tables of stamp
duties and registrable documents. They matter for Stage 3, where sub-section
splitting has to handle them without exceeding 450 tokens per chunk.

### Known gaps

- **No PART/CHAPTER hierarchy yet.** `statute_parts` is empty. India Code's
  section items carry no chapter field, though the Act-level item reports
  `no_of_chapter`. Deferred: the reader needs it, retrieval does not.
- **Fixture verification is partial by design.** All 44 marginal notes were
  checked against the Act's table of contents and two sections were read in full;
  the other 42 are pinned by SHA-256, not independently re-read.
- Registration Act and Indian Stamp Act have no independent section-count oracle
  (the dataset does not carry them), so their counts rest on India Code alone.

---

## 2026-09-11 · Stage 3 — Cross-links, chunking, embeddings, HNSW

Branch `stage-3-index`. The corpus is now searchable: **877 chunks, all 877
embedded, 503 cross-reference edges, HNSW built.**

### Built

- `services/kb/crossref.py` — deterministic regex extraction of internal
  references ("section 23", "sub-section (2) of section 14", "sections 68 and
  72", "s. 4", "section 53A of the Transfer of Property Act, 1882") resolved to
  section ids. Cross-Act resolution matches an Act title exactly, then falls
  back to the longest known title contained in the captured phrase — which is
  what resolves "the Indian Registration Act, 1908" onto our
  `Registration Act, 1908`.
- `services/kb/chunk.py` — the chunker. One chunk per section where it fits;
  otherwise split on the sub-section / proviso / Explanation / Illustration
  boundaries `parse.segment_section()` already found, greedily re-joining
  adjacent pieces so a section does not shatter into fifteen one-line chunks.
  The `passage:` prefix is built here, at index time.
- `services/kb/embedding.py` — model loading, `embed_passages`, `embed_query`.
  The two e5 prefixes are applied in exactly one place each and nowhere else.
- `services/kb/index.py` — the three passes (`build_links`, `build_chunks`,
  `embed_chunks`), `index_stats`, and the HNSW drop/rebuild.
- CLI: `link`, `chunk`, `embed`, `index` (all three in order), and `stats`
  rewritten to report acts, sections total/in-force, chunks,
  embedded/unembedded, largest chunk in tokens, edge count and index state.
- `/v1/health` now reports `chunks_embedded`, `links`, `vector_index_ready` and
  a derived `retrieval_ready`, which is false mid-bulk-embed — the moment an
  operator most needs to be told that dense retrieval is not available.
- `tests/unit/test_chunker.py` (14 tests) plus two smoke tests.

### Decisions

**Model revisions pinned.** `nyaya-embed-v1` at
`dd24436f0f30a262f30e7457c8d5fc07b9a069c6`, `bge-reranker-v2-m3` at
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, resolved from the Hub at download
time and written into `.env` / `.env.example`. An empty revision now raises
`ConfigError` from `Settings.require_embed_revision()` rather than resolving to
`main`.

**`MODEL_CACHE_DIR` (default `var/model_cache`) is exported as `HF_HOME`** by
`config.py` using `os.environ.setdefault`, so the container's existing
`HF_HOME=/models` still wins. `config.py` is the only module that writes the
environment, for the same reason it is the only one that reads it.

**Omitted sections are not chunked.** India Code keeps repealed provisions as
items to preserve numbering; their bodies are either the word "Repealed." or
law that no longer applies. Citing repealed law as the answer is the worst
failure this product has. 665 of 778 sections are indexed; the other 113 stay
in `statute_sections` so a reader can still show the gap.

**The heading prefix is identical across every chunk of a section** —
`passage: <short title> — <marginal note>. ` — and does not carry the
sub-section label. The split text already begins with `(2)` or `Provided that`,
so the label would be duplicated, and a prefix that varies per chunk makes the
chunks of one section look like different provisions to the reranker.

**Oversized-segment fallback** (the ambiguity flagged before the stage began,
resolved by owner's instruction to use judgement). A sub-section that is itself
over the ceiling — the Stamp Act's duty schedules, s.47 at 29.1k characters — is
split at sentence boundaries (`. ; :`), and at whitespace if that is not enough.
Nothing is dropped or truncated; a test asserts that re-joining the chunks of a
hard-split section reproduces every word in order. Worst case is 21 chunks for
one section.

**`tsvector` is English-only, over the heading plus the body**, with the
`passage:` marker stripped — it is an instruction to the embedding model, not a
word anyone will search for. Hindi stays deferred: PostgreSQL 16 ships no
`hindi` configuration.

**Embeddings are L2-normalised at encode time**, so the HNSW `vector_cosine_ops`
distance and a dot product agree.

### Bugs found and fixed inside this stage

1. **`nyaya-embed-v1` cannot be loaded by `SentenceTransformer(repo)`.** The
   repository was exported with sentence-transformers **5.4.1**, whose
   `modules.json` names `sentence_transformers.base.modules.transformer.Transformer`.
   That package does not exist in the **3.3.1** we pin, so the load dies with
   `ModuleNotFoundError: No module named 'sentence_transformers.base'`. Fixed by
   assembling the three modules explicitly (Transformer → Pooling → Normalize)
   instead of bumping a deliberately pinned dependency. The *pooling mode* is
   still read from the repository's own `1_Pooling/config.json` rather than
   assumed — but that file also had to be translated, because 5.x writes
   `embedding_dimension` where 3.3.1 expects `word_embedding_dimension` and adds
   an `include_prompt` key that 3.3.1's constructor rejects. A dimension check
   against `EMBEDDING_DIM` now runs at load, so a future model swap that returns
   1024 dimensions fails at load rather than at the first insert.
2. **A test asserted the wrong behaviour.** The first version of
   `test_a_proviso_is_never_emitted_without_its_provision_heading` required a
   proviso to be its own chunk. It should not be: when the proviso fits beside
   its sub-section, keeping them together is the correct reading. Split into two
   tests — one that they stay together when they fit, one that the heading is
   carried when they cannot.

### Retrieval evidence

Three hand-written queries, top 5 by cosine over the live index:

*"notice period to terminate a lease"* — TPA s.113 *Waiver of notice to quit*
(0.666), s.110 (0.574), s.106 *Duration of certain leases in absence of written
contract* (0.573), s.111 *Determination of lease* (0.490), Contract Act s.206
(0.459). Correct.

*"when must a rent agreement be registered"* — Registration Act s.17 *Documents
of which registration is compulsory* (0.562), s.47 (0.467), TPA s.4 (0.465),
Registration s.48 (0.457), s.31 (0.449). Correct.

*"is a non-compete after employment enforceable"* — **the right answer, Contract
Act s.27 *Agreement in restraint of trade, void*, is at rank 22 (0.257), not in
the top 5.** Not a chunking or prefix defect: s.27 is one chunk of 166 tokens
with a correct prefix, and the same chunk is **rank 1 (0.596)** for "agreement
in restraint of trade" and **rank 2** for "can an employer stop an employee
working for a competitor after resigning". The phrase "non-compete" appears
nowhere in an 1872 Act, and dense retrieval alone will not bridge that. It is
**rank 1 on BM25** for "restraint of trade non compete". Recorded here rather
than smoothed over: this is precisely the case Stage 4's hybrid + RRF + rerank
exists to fix, and it is the query to re-run as the acceptance test for it.
`RETRIEVAL_TOP_K=30` already covers rank 22.

### Flagged, not fixed (carried forward on the owner's instruction)

1. **`.env` `DATABASE_URL` and `POSTGRES_PORT` say 5432; the container binds
   5433**, and host 5432 is a different PostgreSQL with no `legaledge` role.
   Every host CLI and pytest run in this stage needed an explicit
   `DATABASE_URL=...:5433/...` override. **Consequence: with a stock `.env`, the
   database-backed tests — including the `section_no_sort` ordering suite, a
   non-negotiable — skip silently rather than fail.**
2. **An API image was already built** (`legaledge-api`) in a previous session,
   against the note's "build only at Stage 4 and 9".
3. **`statute_parts` is still empty**, so `Chapter IV` / `Part XII` references
   cannot resolve (30 of them).
4. The manifest is TOML, not the approved-but-unused PyYAML.

### Unresolved references — recorded, not dropped

218 in total, all in the `ingest_runs` row for `command='link'`:

| kind | count | what it is |
|---|---:|---|
| `section_not_found` | 122 | mostly IPC/CrPC references made without naming the Act ("section 506"), plus state-amendment text India Code inlines into the central Act (Karnataka's "new section 19A" inside Registration Act s.19) |
| `act_not_in_corpus` | 66 | genuine references outside our six — Indian Evidence Act 1872, Banking Regulation Act 1949, State Bank of India Act 1955 |
| `no_part_hierarchy` | 30 | `Chapter`/`Part` references, unresolvable until `statute_parts` is populated |

### Known gaps at the end of Stage 3

- **`bge-reranker-v2-m3` has not been downloaded.** Its revision is pinned and
  `require_rerank_revision()` is wired, but nothing loads it until Stage 4. It
  may need the same explicit-module treatment as the embedder — check its
  `modules.json` before assuming `CrossEncoder(repo)` works.
- **No `search` verb.** Retrieval was exercised by script for the evidence
  above; the query path proper is Stage 4 and the read API is Stage 5.
- **The HNSW rebuild is not concurrent.** `embed_chunks` drops the index for the
  duration of a bulk load, so dense retrieval is unavailable while it runs. That
  is what `retrieval_ready` on `/v1/health` reports. Fine for a CLI pipeline; it
  would not be fine for a live re-index, which nothing yet does.
- **`section_explanations` and `statute_parts` remain empty** (Stage 8 and
  deferred, respectively).

### What Stage 4 needs

- `embed_query(settings, question)` applies `query:`; do not add it at the call
  site. `embed_passages` refuses a string without `passage:`.
- Dense: `kb_chunks.embedding <=> :vec` with `vector_cosine_ops`. Sparse:
  `ts_rank(kb_chunks.tsv, plainto_tsquery('english', :q))`. Both indexes exist.
- `statute_links` is populated, so pulling a referenced section into context is
  a join, not another retrieval.
- The **Docker image build is due this stage**. Nothing new is needed from the
  system packages side: torch, transformers and sentence-transformers were
  already pinned in `pyproject.toml` from Stage 0 and no new dependency was
  added. `MODEL_CACHE_DIR=/models` was added to the Dockerfile beside the
  existing `HF_HOME=/models`, so the `model-cache` volume is what the container
  reads. Expect the first container run to download the weights once.
- The abstention gate and the citation validator are the product claim. The
  "non-compete" query above is the acceptance test for whether hybrid retrieval
  actually earns its place.

---

## 2026-09-11 · Stage 4 — Minimal `POST /v1/ask`

Branch `stage-4-ask`. The milestone: a question goes in, and either a grounded
answer with validated citations comes out, or an honest abstention does —
with no model call made on the abstention path.

### Built

- `services/retrieval/hybrid.py` — dense (pgvector cosine) + sparse (`ts_rank`)
  + Reciprocal Rank Fusion at `k=60`. RRF fuses on *rank*, not score: a cosine
  of 0.66 and a `ts_rank` of 0.10 are not comparable numbers and normalising
  them into one scale is a hyperparameter nobody can calibrate.
- `services/retrieval/rerank.py` — `BAAI/bge-reranker-v2-m3` cross-encoder at
  its pinned revision, sigmoid applied so the score is a 0-1 number comparable
  against `RERANK_SCORE_FLOOR`.
- `services/answer/abstain.py` — the gate. ~25 lines, runs before any model call.
- `services/answer/pack.py` — expand each surviving chunk to its whole parent
  section plus one hop of `statute_links`, order by statute then
  `section_no_sort`, fit to the context budget.
- `services/answer/citations.py` — the validator.
- `services/answer/prompt.py` — versioned system prompt (`ask-v1`).
- `services/llm/client.py` — LiteLLM, with every provider failure mapped onto
  the typed hierarchy.
- `services/answer/pipeline.py` — orchestration.
- `api/v1/ask.py` + `schemas/ask.py` — the route.
- `tests/unit/test_citations.py` (10) and `tests/unit/test_abstention.py` (10),
  plus three smoke tests. 117 tests green.

### Decisions

**Citation ids are `[S<section_id>]`, not bare integers.** India Code renders
footnotes as bare `[1]`, `[2][State Government]`, and those markers are *inside*
the blocks handed to the model. A bare-integer scheme would make the validator
argue with the statute's own footnotes forever. A test pins this.

**An answer with no citations fails validation.** Not only fabricated ids: an
assertion about the law with no provision behind it is exactly the output this
product exists not to produce. It triggers the same single retry.

**`citation_violation` means fabrication specifically**, not "a retry happened".
A `no_citations` first attempt that retries successfully reports `false`.

**The provider key is required *after* the gate, never before.** An
out-of-corpus question therefore needs no key at all and costs nothing — which
is both the spec's intent and a nice property to be able to demonstrate.

**`LLM_MODEL` defaults to `anthropic/claude-sonnet-4-5`** (owner's choice this
session). `LLM_API_KEY` ships empty in both `.env` and `.env.example`; the
owner supplies it directly so it never passes through a transcript.

**The highest-priority block is always packed, even if it alone exceeds the
budget.** Found while writing the packing test: Indian Stamp Act s.47 is 29k
characters, roughly 7k tokens. Dropping the very section the reranker chose
would abstain on a question we had in fact retrieved the answer to. Overflowing
a 12k budget into a 200k context window is the lesser problem.

### Bugs found and fixed inside this stage

1. **The sparse retriever was returning zero rows — hybrid search was running
   on one leg.** `websearch_to_tsquery` (and `plainto_tsquery`) join unquoted
   terms with **AND**, and no statute contains every word of "is a non-compete
   after employment enforceable" at once. Measured: 0 chunks matched with AND,
   **117 with OR**. Fixed by lexemising the question with `to_tsvector` (so the
   stemmer and stopword list are Postgres's) and ORing the lexemes, with
   `nullif` guarding an all-stopwords question against a tsquery syntax error.
   After the fix, "when must a rent agreement be registered" surfaces TPA s.107
   *Leases how made* at sparse rank 1 — a provision dense retrieval had at rank
   8. This was invisible from the code and only showed up as `sparse=0` in a
   live run.
2. **The first Docker build failed while reporting success.** The build ran in
   a compound shell command whose exit code came from the trailing `tail`, so a
   `DeadlineExceeded` pulling the BuildKit frontend — network contention with
   the 3.3 GB reranker download — was reported as exit 0. Rebuilt serially.
   Worth remembering: check the build's own exit status, not the wrapper's.

### Retrieval evidence — `POST /v1/ask`, live

| Question | Result |
|---|---|
| "When must a lease of immoveable property be registered?" | gate **passed** — TPA s.107 *Leases how made* 0.991, Registration s.17 0.983/0.978, s.18 0.945, s.49 0.774; 12 of 43 candidates above the floor → **402 `missing_provider_key`** (no key configured) |
| "What notice terminates a lease for agricultural purposes?" | gate **passed** — TPA s.117 *Exemption of leases for agricultural purposes* 0.941, s.106 0.928, s.37 0.854; 3 of 53 above floor → **402** |
| "What is the capital gains tax rate on a flat in Mumbai?" | **200 abstained**, top score 0.0037, 0 of 49 above floor, no model call |
| "What did the Supreme Court hold in Kesavananda Bharati?" | **200 abstained**, top score 0.0010, 0 of 48 above floor, no model call |
| "Is an agreement not to compete after leaving employment enforceable?" | **200 abstained**, top score 0.0248, 0 of 52 above floor — see below |

The floor of 0.30 separates cleanly on this evidence: genuine matches land at
0.77-0.99 and out-of-corpus questions top out at 0.004. It was not tuned to
produce that; it is the value that was already in `.env`.

### The finding that matters: a vocabulary gap, not a pipeline defect

Contract Act s.27 *Agreement in restraint of trade, void* is the correct answer
to a non-compete question, and the pipeline abstains on it. Isolated by
re-asking the same legal question in four ways:

| Phrasing | s.27 rerank score | rank | outcome |
|---|---:|---:|---|
| "Can a contract restrain someone from carrying on a lawful profession?" | **0.987** | 1 | answers |
| "Is an agreement in restraint of trade enforceable?" | **0.817** | 2 | answers |
| "Is an agreement not to compete after leaving employment enforceable?" | 0.014 | 4 | abstains |
| "non-compete clause after employment" | ~0.000 | 25 | abstains |

So retrieval, fusion, packing and the gate are all correct — s.27 is *in* the
candidate set every time. `bge-reranker-v2-m3` simply does not connect the
commercial term "non-compete" to the statutory term "restraint of trade". Three
honest options, none taken unilaterally:

1. **Stage 6's query rewriting** is the natural fix and is already planned — it
   rewrites the question before retrieval, and a rewrite into statutory
   vocabulary is exactly what closes this.
2. **Measure `nyaya-reranker-mini-v1` on precisely this case.** ADR 0001 ruled
   it out on aggregate recall@1, which was right on the evidence available —
   but it is fine-tuned on Indian Acts and this is an Indian-legal-vocabulary
   failure. The reranker is already swappable by config.
3. Lowering the floor does **not** work and should not be tried: s.27 scores
   0.014 on the failing phrasing while the out-of-corpus top score is 0.0037.
   No floor separates those two by enough to be safe.

### Non-functional: reranking is ~100× over the latency target

Measured on this laptop's CPU: retrieval 0.8-4.2 s, **reranking 33-50 s** for
43-59 candidates, end-to-end `/v1/ask` 46-55 s. Spec §06 wants p95 under 400 ms
for the whole hybrid-plus-rerank path. This is not a tuning problem — it is a
24-layer cross-encoder scoring ~50 pairs of up to 512 tokens on CPU. Options for
Stage 9: a GPU, ONNX Runtime with int8 quantisation, cutting `RETRIEVAL_TOP_K`,
or the mini reranker. Recorded now with numbers so the decision is made against
data rather than rediscovered during deployment.

### Known gaps at the end of Stage 4

- **Generation and live citation validation are unverified end to end.**
  `LLM_API_KEY` is empty, so no real completion has been produced. The validator
  has ten unit tests and the abstention gate ten more, but nothing has yet
  checked that this prompt, with these blocks, makes a real model emit
  `[S<id>]` in the expected form. That is the first thing to do once a key is in
  `.env`, and if the model prefers some other citation shape the prompt — not
  the validator — is what changes.
- **No `ask_logs` row is written** (Stage 6, with SSE and query rewriting).
  `turns` is accepted and ignored; the response says so via `turns_used: false`.
- **LiteLLM fetches its pricing table from GitHub on first use.** An outbound
  call on the request path that nothing in this design needs. Pin or disable it
  in Stage 9.
- **No rate limiting** on an endpoint that spends the operator's money (Stage 9).
- The `.env` port mismatch flagged in Stage 3 is still present and unfixed.

### What Stage 5 needs

- `POST /v1/search` is `hybrid_search` minus the reranker, minus the LLM — the
  retrieval half is already a reusable function taking a session and settings.
- `GET /v1/statutes/{slug}` wants the part/chapter tree, and `statute_parts` is
  still empty. That gap now has a user-visible consequence for the first time.
- Every Stage 5 endpoint is keyless by spec §06, which the current code already
  satisfies: only `/v1/ask` ever touches `require_api_key`.

---

## 2026-09-11 · Stage 5 — Corpus read API and search

Branch `stage-5-corpus-api`. Five keyless endpoints. Reading the law is free;
only `/v1/ask` spends anyone's money, which spec §06 requires and the code now
structurally guarantees — `require_api_key` is reachable from exactly one route.

### Built

- `GET /v1/statutes` — the six Acts with year, jurisdiction, ministry, in-force
  section count, as-of date, repeal status and provenance URL.
- `GET /v1/statutes/{slug}` — one Act plus its full section index in citation
  order, `sections_total` vs `sections_in_force`, and the Part/Chapter tree.
- `GET /v1/statutes/{slug}/sections/{no}` — one section verbatim.
- `GET /v1/sections/{id}` — the same by id; what an `[S<id>]` citation chip
  resolves against.
- `POST /v1/search` and `GET /v1/search` — hybrid search, one row per section.
- `services/corpus_read.py`, `schemas/corpus.py`, `api/v1/corpus.py`,
  `tests/integration/test_corpus_api.py` (6 tests). 123 tests green.

### Decisions

**Search does not rerank, and says so in the payload.** `reranked: false` is a
field, not an omission. The cross-encoder costs 30-50 seconds on this CPU
(measured in Stage 4); a search box that takes a minute is not a search box.
Search returns RRF fusion order, which the evidence below shows is good enough
for a ranked list. `/v1/ask` still reranks, because there the cost buys the
abstention decision.

**Search collapses chunks to sections.** Registration Act s.17 is four chunks;
four rows for one provision is a worse result list, not a richer one. The
best-scoring chunk wins and supplies the snippet.

**Omitted sections are excluded from search but included in an Act's index.**
A reader browsing the IT Act needs to see that s.66A exists and is omitted, or
the numbering looks broken. A reader searching does not want repealed law in
their results. Same data, two correct answers, one flag (`include_omitted`).

**Snippets are the head of the matched chunk, not `ts_headline`.** Half the
hits come from the dense retriever and contain none of the query's words, so
highlighting would make the field mean "fragment around your terms" for lexical
matches and "arbitrary opening" for semantic ones. One meaning is worth more
than one clever feature.

**Section lookup is by normalised number.** `21A`, `21-A` and `21 a` all reach
the same provision, reusing `crossref.normalise_section_no`. Legal citation is
not consistent about this and a reader typing the form they saw in a judgment
should not get a 404. Verified live against IT Act `66a` → `66A`.

**`GET /v1/search` exists alongside the POST form** so a result page is a URL —
linkable, and cacheable in Stage 9.

### ❌ Blocked: the Part/Chapter tree

Spec §06 says `GET /v1/statutes/{slug}` returns "one Act with its part and
chapter tree" and that it "powers the browser's navigation". It returns
`parts: []`. This is not deferred work — **the data does not exist in the
source we hold**, established by three checks rather than assumed:

1. Every metadata key across all 919 archived India Code items: there is
   `dc.identifier.no_of_chapter` on the *Act* item (a count, 19 occurrences)
   and nothing per section. No chapter, no part, no parent.
2. `dc.identifier.order_number` gives sequence, not hierarchy.
3. No section's `text_verbatim` or `marginal_note` contains the string
   `CHAPTER` at all — 0 of 778 — so the headings are not recoverable from the
   text either.

So the tree is genuinely *unknown*, not merely unloaded, and the response says
that in a field: `parts_available: false`. An empty list on its own would be
read by a client as "this Act has no chapters", which is false for all six.
Populating it needs a different source — the Act PDF's table of contents, which
India Code does attach — and that is a parsing job of its own, not a line of
SQL. Flagged for a decision rather than guessed at.

### Evidence — every endpoint, live

```
GET /v1/statutes                      200   88ms   6 acts
GET /v1/statutes/dpdp-act-2023        200   13ms   44/44 in force, index of 44
GET .../indian-contract-act-1872/sections/27    200  s.27 "Agreement in restraint of trade, void."
GET .../information-technology-act-2000/sections/66a  200  s.66A, is_omitted=true  (normalisation works)
GET /v1/sections/999999               404   not_found
GET /v1/statutes/not-an-act           404   not_found
```

Cross-reference expansion, both directions:

```
Registration Act s.17   -> 14 related (inbound from s.1, s.18, s.22, s.28, s.34, s.49 ...)
TPA s.53A               ->  1 related (inbound from Registration Act s.17 -- cross-Act)
Contract Act s.23       ->  1 related (inbound from TPA s.6 -- cross-Act)
Registration Act s.89   -> 17 related (both directions)
```

Search, RRF order, no reranker:

| Query | Top hits | Time |
|---|---|---|
| "restraint of trade" | **Contract s.27** (d1/s1), s.26, s.28, s.1, s.29 | 4.9 s cold / — |
| "when must a rent agreement be registered" | Registration s.48, **TPA s.107 *Leases how made*** (sparse rank 1), Registration s.17, TPA s.116 | 76 ms |
| "reasonable security safeguards for personal data" | **DPDP s.8 *General obligations of Data Fiduciary*** (d1/s1), **IT Act s.43A *Compensation for failure to protect data*** (d2/s2), DPDP s.17, IT s.66F | 87 ms |

The third query is the one worth noting: it finds the right provision in *two
different Acts* passed twenty-three years apart, which is the thing a hybrid
index over a mixed corpus is supposed to do and a keyword search would not.

The 4.9 s on the first query is the embedding model loading on first use, not
per-query cost; every subsequent search is 76-87 ms. Worth making an explicit
warm-up in Stage 9 so the first user of a fresh process does not pay it.

### Known gaps at the end of Stage 5

- **The Part/Chapter tree** — see above. Needs a decision.
- **No caching.** Spec §06 wants statute metadata and section reads served from
  cache under 300 ms. They are already 13-88 ms uncached on six Acts; the ETag
  and Redis work stays in Stage 9 where it was scheduled.
- **Search has no pagination** — `limit` up to 100, no offset. Six Acts and 877
  chunks do not need it; twenty Acts would.
- **`explanation` is always null** on a section read. Stage 8 fills it.
- **Search is not exercised in the test suite**, only against the live corpus
  (evidence above). Testing it would mean embedding a fixture, which loads the
  1.1 GB model into a unit-test run — exactly what the "never let a test
  trigger a download" rule is there to prevent. The read endpoints around it
  are tested on seeded rows.
- Still carried and unfixed, at the owner's instruction: the `.env` port
  mismatch (5432 vs 5433), **`LLM_API_KEY` empty so generation and live
  citation validation remain unverified**, and **`/v1/ask` at 46-55 s against a
  400 ms target**.

### What Stage 6 needs

- SSE on `/v1/ask`: `llm.complete` is the only non-streaming call, and LiteLLM's
  `acompletion(stream=True)` is the change. The citation validator runs on the
  *assembled* answer, so the abstention-on-second-violation path has to buffer
  or emit a correction event — worth deciding before writing it.
- Query rewriting from `turns` goes in front of `hybrid_search` in
  `pipeline.answer_question`, and is the natural fix for the "non-compete" ↔
  "restraint of trade" vocabulary gap recorded in Stage 4.
- `ask_logs` is ready and anonymous by construction; `AskResult` already carries
  every column it needs (`top_score`, `citation_violation`, `model`, tokens,
  `latency_ms`).
