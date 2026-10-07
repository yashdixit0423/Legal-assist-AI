# Handoff — Chat fix phase (stopped 2026-10-07)

Work stopped mid-phase to move to another machine. Branch `chat-fix-wip` is
`LegalEdge-1.1-Yash` plus one WIP commit and this file. Nothing below was
pushed before this handoff except this branch.

## Status

| Item | Status | Commit(s) | Notes |
|---|---|---|---|
| F1 Lazy-load Chat | ✅ done | `8472b68` | Main bundle 664.08 kB → 385.76 kB (gzip 205.16 → 120.57); Chat chunk 280.42 kB (gzip 86.12). react-markdown/remark-gfm only in the Chat chunk. |
| F2 Upload limit while reading | ✅ done | `afc388a` | Incremental multipart reader; aborts at 10 MB with `file_too_large`; Content-Length pre-check kept. Tests: reader stops within one 64 KB chunk with peak ≤ limit; exactly-10 MB accepted; 11 MB streamed (no length) → 413. |
| F3 Mixed doc + law | 🔄 partial | `781e84c` (WIP tests only) | Diagnosis done, regression tests written; no code change yet; gold baseline not captured. See below. |
| F4 PDF page cap (100) | 🔄 partial | `f0f04a5` | Cap, typed `document_too_long` (413, "This PDF has N pages; the limit is 100."), ADR 0005 amended, test for 100 vs 101 pages. **Left:** measure upload+processing time of a ~100-page text PDF; check the message in the Chat UI. |
| F5 Cleanup | 🔄 partial | — (nothing to commit) | Done: `var/chat-test-account.json` deleted; test user `chat-test-…@example.test` deleted from the local DB (0 credentials, 1 user); every process on :8000/:8080 and the gold eval stopped. **Left:** the browser smoke test still needs a fresh temporary account, which must be deleted afterwards. |
| Multi-worker warning | ✅ done | `fa1e6cf` | Logs `chat_documents_single_process_only` at startup when `WEB_CONCURRENCY`, `UVICORN_WORKERS` or `--workers/-w` > 1. Tests for detection and the log. |
| Test isolation | 🔄 partial | `781e84c` | conftest forces provider key vars to `""` and stubs `litellm.acompletion/completion` to raise `UnmockedLLMCallError`; `tests/unit/test_llm_isolation.py` added. **Not yet run.** |

## Partial items: what is left and the exact next step

### F3 — mixed document + law questions
- **Done.** Read `_prepare` in `apps/api/app/services/answer/pipeline.py`. Two tests in
  `tests/unit/test_chat_documents.py` (`test_a_mixed_question_cites_the_law_and_the_document`,
  `test_the_statute_floor_is_unchanged_when_a_document_is_attached`) passed individually
  on the old conftest.
- **Findings so far.** The statute gate *already* scores the question alone:
  `hybrid_search → rerank → apply_floor` runs on `rewrite.question` before
  documents are considered, and document passages have their own selection and
  budget. So a document cannot suppress statutes in code. The suspected cause of
  the earlier miss ("My lease is for eleven months. Must it be registered, **and
  what rent does it set?**") is the extra document-specific clause lowering the
  cross-encoder score below `RERANK_SCORE_FLOOR`. **Not yet measured.**
- **Planned fix.** Only when documents are attached, also score the statute gate
  against a law-only form of the question (clause split / stripping
  document-specific clauses, or the existing rewrite step) and take the better
  score per candidate. `RERANK_SCORE_FLOOR` and the citation validator stay unchanged.
  The law-only path stays untouched, so gold metrics should not move.
- **Exact next step.**
  1. Run the probe that was written but not run (it was in the session scratchpad;
     recreate it): for each of "My lease is for 11 months — must it be registered?"
     and the eleven-month/rent question, print the top reranker score for the full
     question and for each clause. Run nothing else model-heavy at the same time.
  2. Capture the gold baseline: `.venv/bin/legaledge-kb eval-gold --fresh --out var/eval/gold-before.json`.
  3. Implement the law-only scoring in `_prepare` (documents path only), re-run the
     probe (before/after scores), then `eval-gold --fresh --out var/eval/gold-after.json`.

### Test isolation
- **Next step:** `.venv/bin/pytest -q`. Expect every existing test to pass and
  `test_llm_isolation.py` to pass. If a test fails with `UnmockedLLMCallError`, it was
  calling a real provider: mock `llm.complete`/`llm.stream` in it. Then run once with
  outbound network blocked to confirm (for example, set `HTTPS_PROXY=http://127.0.0.1:9`).

### F4 — timing
- **Next step:** generate a 100-page text PDF with pymupdf, `POST /v1/chat/documents` against
  the running API, and record the wall time in docs/BUILD-LOG.md; upload a 101-page PDF
  in the Chat UI and confirm the chip shows the message.

### Rest of the fix-phase run order (not started)
Full `ruff/format/mypy/pytest`, frontend `typecheck/build`, `bash start.sh` in the
background, health check, the browser smoke test (law question + panel, follow-up, TXT
upload, mixed lease question, oversized file, 101-page PDF), leave the app running, and
the end-of-phase report.

## Gold eval baseline
**Not captured.** A fresh run was stopped at 135 of 139 cases, so no report was
written. For reference only, the previously committed `eval/gold/report-mini.json`:
recall@1 84.1%, @3 92.5%, @6 94.4%, @10 97.2%; MRR 0.890; abstention accuracy 90.6%;
false abstention 3.7% (139 cases). It was not re-measured on this code.

## Known issues
- **Tests read the real LLM key from `.env`** (pydantic-settings `env_file=".env"`) unless a
  real environment variable overrides it. During this phase, one F3 test run with only
  `llm.complete` mocked made **one real provider call** through `llm.stream` before it was fixed.
  The WIP conftest guard fixes this but has not been run.
- **The 8 GB machine swaps during the gold eval** (about 10 GB of swap in use). Running pytest or other model
  work alongside it slowed cases from ~2 s to ~2 min. Run the eval on its own.
- On stopping, a port sweep with `lsof -ti` also killed a Claude desktop helper process that
  held a client connection to :8000/:8080. Use `lsof -ti -sTCP:LISTEN` next time.
- Earlier known issues still stand (see BUILD-LOG): app-wide `--ink-3/--ink-4` contrast below
  WCAG AA (left as decided); server-side streaming is buffered; voice transcription not
  verified in a real browser.
