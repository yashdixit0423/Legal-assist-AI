# LegalEdge Phase 1.1 — session note, 2026-09-11

A record of one session that took the build from "Stage 3 not started" to a
running product with a web client. Written so a session with no other context
can pick it up.

**Repository:** `yashdixit0423/Legal-assist-AI`, branch `LegalEdge-1.1-Yash`
(plus one branch per stage). 39 commits.

---

## 1 · Where it started and where it ended

| | Start of session | End of session |
|---|---|---|
| Stages complete | 0, 1, 2 | **0 through 9** |
| Tests | 78 | **207** |
| Corpus | 6 Acts parsed, nothing indexed | 6 Acts · 778 sections · 877 chunks, all embedded · 503 cross-references |
| API | `/v1/health` only | 16 endpoints: ask, search, corpus reads, auth, credential vault |
| Frontend | none | React client wired to the live API, verified in a browser |
| Measured quality | none | recall@6 **94.4%**, abstention **90.6%**, over a 139-case gold set |

Source files now: 70 Python, 23 TypeScript (excluding shadcn primitives), 13
test files, 4 ADRs, a 1,921-line build log.

---

## 2 · What was built, stage by stage

### Stage 3 — Index
Cross-reference extraction into `statute_links` (503 edges, regex, no LLM;
unresolvable references recorded rather than dropped — 218 of them, by kind).
Chunker applying the e5 `passage:` prefix at index time, splitting on
sub-section/proviso/Explanation boundaries with the parent heading carried onto
every split. 877 chunks, none over the 450-token ceiling. Embeddings via
`nyaya-embed-v1` at a pinned revision, HNSW built once after a bulk load.
English `tsvector` for BM25.

**Bug found:** `nyaya-embed-v1` cannot be loaded by `SentenceTransformer(repo)`
— the repository was exported with sentence-transformers 5.4.1, whose
`modules.json` names classes under `sentence_transformers.base`, a package that
does not exist in the pinned 3.3.1. Fixed by assembling Transformer → Pooling →
Normalize explicitly rather than bumping a deliberately pinned dependency.

### Stage 4 — `POST /v1/ask`
Hybrid retrieval (dense + BM25, Reciprocal Rank Fusion at k=60), cross-encoder
rerank, the abstention gate, context expansion to whole parent sections plus one
hop of cross-references, packing with citation ids, generation through LiteLLM,
and the citation validator.

**Bug found:** the sparse retriever was returning **zero rows**, so hybrid
search had been running on one leg. `websearch_to_tsquery` ANDs unquoted terms
and no statute contains every word of a natural question — 0 matches with AND,
117 with OR. Fixed by lexemising the question with `to_tsvector` and ORing.

### Stage 5 — Corpus read API
`GET /v1/statutes`, `/v1/statutes/{slug}`, section reads by number and by id,
`POST|GET /v1/search`. All keyless per spec §06.

**Blocked, honestly:** the Part/Chapter tree. Established by three checks, not
assumed — no per-section chapter field across 919 archived India Code items, and
the string `CHAPTER` appears in 0 of 778 section texts. Returns
`parts_available: false` so a client does not read an empty list as "no chapters".

### Stage 6 — SSE, query rewriting, `ask_logs`
Streaming selected by the `Accept` header, with citations validated **mid-stream**
rather than at the end: the moment a `[S…]` id appears that was not in the
prompt, the stream is abandoned and an `invalidated` event tells the client to
discard what it rendered. Query rewriting from prior turns, failing open in every
error path. One anonymous `ask_logs` row per question.

### Stage 7 — Auth and the BYOK vault
Argon2id passwords, JWT with a checked `typ` claim, and an AES-256-GCM vault
where the user id and provider are authenticated as associated data — a row
moved between accounts fails to decrypt rather than handing over the wrong key.
Write-only, enforced in the type system as well as the service layer.

**Bug found:** a 204 route annotated `-> None` broke **application startup**
(Starlette asserts a 204 has no body), which surfaced as six unrelated test
failures from one cause.

### Stage 8 — Gold set and metrics
139 hand-labelled questions: 107 in-corpus across all six Acts, 32 adversarial
covering case law, foreign law, tax rates, opinion, and two subjects *repealed
out of* our own corpus. Every label is resolved against the database before a
single metric is computed.

### Stage 9 — Hardening
Rate limiting (fixed window, Redis-backed with an in-process fallback, failing
open), ETags with 304s on corpus reads, model warm-up at start-up, the
`MODEL_DEVICE` switch, and LiteLLM's outbound pricing fetch disabled.

---

## 3 · Measured results

Gold set, `nyaya-reranker-mini-v1`, 139 cases in **4 minutes 30 seconds**:

| Metric | Value | Spec §10 bar |
|---|---:|---|
| recall@1 | 84.1% | — |
| **recall@6** | **94.4%** | ≥ 85% ✅ |
| recall@10 | 97.2% | — |
| MRR | 0.8901 | — |
| abstention accuracy | 96.9% at floor 0.60 | ≥ 95% ✅ |
| false abstention | 8.4% | — |
| fabricated citations | 0 across the live runs | must be 0 |

**The score floor was calibrated, not guessed.** It was inherited as 0.30 and
never measured. Because the runner caches per-candidate scores rather than
verdicts, sweeping it costs a JSON re-read:

| Floor | Abstention | False abstention |
|---|---:|---:|
| 0.30 (inherited) | 90.6% | 3.7% |
| **0.60 (chosen)** | **96.9%** | **8.4%** |
| 0.70 | 96.9% | 11.2% |
| 0.75 | 100% | 14.0% |

0.65 and 0.70 give the identical 96.9% for more false refusals, so both are
strictly dominated. 0.60 is the cheapest point that clears the bar.

---

## 4 · The bugs that only running found

Eleven defects reached production-shaped code and were caught by execution, not
review. The pattern is worth noting: **every one was invisible to inspection.**

1. **The citation validator ignored real citations.** `gpt-4.1-mini` wrote
   `[S19(c)]` and `[S18(1)(d), S1107]`. The pattern required `]` immediately
   after the digits, so the first was **not seen as a citation at all**. A
   fabricated `[S9999(c)]` would have passed validation in silence — in the one
   component the brief calls the product claim. It had ten passing unit tests;
   they tested the forms *I* imagined.
2. **The sparse retriever returned zero rows** (see Stage 4).
3. **`check-config` printed the provider key in full.** The secret list predated
   `LLM_API_KEY`. `DATABASE_URL` and `REDIS_URL` leaked the same way.
4. **CORS was missing entirely**, and `expose_headers` with it — browsers hide
   all but a safelist of response headers from JavaScript, so the rate-limit
   counter would have silently never appeared.
5. **`sse-starlette` writes CRLF.** Splitting frames on `\n\n` matched nothing,
   so the UI sat on a spinner while the server streamed perfectly. Found with
   `od -c`, not by reading.
6. **15 database tests were skipping silently** because `conftest.py` hardcoded
   port 5432 — including the `section_no_sort` suite, one of the four pillars.
7. **A 204 route broke application startup** (see Stage 7).
8. **`provider_of` was never written** — a `str.replace` silently no-opped
   against text `ruff` had already reformatted.
9. **`new URL().pathname` percent-encoded the space** in "legaledge 1.1".
10. **`.section-panel` carried `min-height: 420px`** — a reading panel misused
    as a list row.
11. **The config contradicted its own ADR**: ADR 0004 made mini the default
    reranker, but the backend ran bge while using the 0.60 floor calibrated
    against mini. Two models behind one calibration.

---

## 5 · Where I was wrong, and what corrected me

Recorded because the pattern matters more than the individual errors: **every
estimate I made from a microbenchmark or from memory was wrong, usually by
3–8×, and always optimistic.**

| Claim | Reality | Corrected by |
|---|---|---|
| "MPS will be 3–8× faster" | 1.7× | measuring it |
| "The gold run needs 65 more minutes" | 141, and rising | measuring the *recent* rate, not the average |
| "bge will take 29 minutes" | 88 s/case → 203 min | a 20-case probe |
| "Cap Docker to free 2.8 GB" | frees 200–300 MB | Docker's *actual* RSS is 1.28 GB, not its 3.82 GB ceiling |
| "float16 halves memory, so it helps" | 10× **slower** on CPU | PyTorch emulates fp16 there |
| "The generated package.json is fictional" | mostly valid | my version knowledge was stale — TypeScript *is* at 7.0.2 |
| "Tests fail if `apps/web` appears" | no such test | it was deleted in the Stage-2 scope cut |

The one estimate that held was the 20-case probe. It cost 10 minutes and saved
3.4 hours. **Probe, do not extrapolate.**

---

## 6 · The frontend

Started from the Builder.io reference. Its visual design is good and was kept
almost untouched — palette, shadcn primitives, component decomposition. Its data
layer was entirely fictional: zero `fetch`/`EventSource` calls anywhere, and a
167-line `legal-data.ts` that cross-referenced the **Specific Relief Act, which
is not in the corpus** and whose citation chip could never have resolved.

Deleted: the mock data, the Express server, and `ModelSelector` (a control wired
to nothing — the backend reads one `LLM_MODEL` and exposes no model list).
Added: a typed API client transcribed from the live OpenAPI, auth with refresh
discipline, an SSE reader, and the four screens the reference lacked entirely —
login, register, search, and a section route for citation chips to land on.

**Verified in a browser against the live API**, not asserted: six real Acts;
citation order with `19A` between `19` and `20`; a grounded answer citing TPA
s.106 with a working chip and a `921 in / 108 out / 8.2s` footer; and an
out-of-corpus question abstaining at HTTP 200 with *"best match scored 0.0060,
required 0.60 or better — no model was called, so this question cost nothing."*

---

## 7 · Decisions recorded as ADRs

- **ADR 0001** — retrieval models (pre-existing)
- **ADR 0002** — backend-only scope (pre-existing)
- **ADR 0003** — identifiers and citation ordering (pre-existing)
- **ADR 0004** — *new*: `nyaya-reranker-mini-v1` is the default reranker below
  ~12 GB of usable memory. ADR 0001 chose bge partly because "we are not
  size-constrained"; measurement falsified that premise on this hardware. bge
  remains preferred where memory allows and is one environment change away.

---

## 8 · What is outstanding

**Needs a decision, not work:**

- **p95 latency.** Spec §06 wants < 400 ms for hybrid+rerank. Measured: ~1.7 s
  (mini) and 2.75 s p95. Unreachable by tuning — a cross-encoder runs one
  forward pass per candidate. Either accept that a grounded legal answer takes
  seconds, or change shape (ONNX int8, fewer candidates, a smaller model).
- **bge's gold numbers.** Not obtainable on an 8 GB host; four configurations
  were tried and all swapped. Needs a machine with more memory.
- **A frontend beyond this one**, if wanted — the current client is complete
  for the endpoints that exist.

**Known gaps, documented:**

- Citation correctness at scale (spec wants human scoring of 150 answers) and
  the fabricated-citation rate over 300 questions — both unmeasured.
- Part/Chapter tree ❌ blocked on absent source data.
- No token revocation; a stolen refresh token is valid 14 days.
- `ask_logs` records nothing for 402/provider errors, so Stage 8 metrics
  undercount attempted questions.
- Model listing on `/v1/credentials/verify` not implemented.
- `CREDENTIAL_ENC_KEY` rotation modelled (`key_version`) but nothing re-encrypts.
- Registration is open — no email verification.
- Sentry and Langfuse unwired.
- Explanations job, Ragas and Hindi remain deferred by the agreed scope cut.

---

## 9 · Running it

```bash
# 1. database
cd "/Users/yashdixit/Desktop/legaledge 1.1" && docker compose up -d postgres

# 2. api
cd "/Users/yashdixit/Desktop/legaledge 1.1" && .venv/bin/uvicorn app.main:app --app-dir apps/api --port 8000

# 3. web client
cd "/Users/yashdixit/Desktop/legaledge 1.1/legalai_frontend" && npm run dev
```

Then http://localhost:8080 for the UI, http://localhost:8000/docs for the API.

Two questions that exercise opposite paths:

- *"When must a lease of immoveable property be registered?"* — answers, citing
  Registration Act s.17 and Transfer of Property Act s.107.
- *"What is the capital gains tax rate on a flat in Mumbai?"* — abstains, with
  no model call at all.

Re-run the evaluation:

```bash
cd "/Users/yashdixit/Desktop/legaledge 1.1" && .venv/bin/legaledge-kb eval-gold --out eval/gold/report-mini.json
```

Sweep the score floor without recomputing anything:

```bash
cd "/Users/yashdixit/Desktop/legaledge 1.1" && .venv/bin/legaledge-kb eval-gold --floor 0.70
```

---

## 10 · The one thing to carry forward

The product claim is that answers come only from statute text that was actually
retrieved, with citations checked in code against exactly what went into the
prompt — and an honest refusal when the corpus does not cover the question.

Every part of that is now demonstrated end to end rather than asserted. The
piece most worth guarding is the citation validator: it was the component with
the most tests and it still had a hole that only a real model found. Tests
written by the author of a parser cannot find the inputs the author did not
imagine. Run it against something real.
