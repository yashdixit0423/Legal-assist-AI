# Handoff — Chat fix phase (completed 2026-10-07)

The phase was started on one machine, stopped mid-way (commit `dd1205e`), and
finished on a second machine: Windows 10, 31.7 GB RAM, CPU only, native
PostgreSQL 16 + pgvector 0.8.7 instead of Docker. Branch `chat-fix-wip`; not
merged into `main`. Full measurements are in docs/BUILD-LOG.md, entry
"Chat fix phase — F3, F4 timing, test isolation (new machine)".

## Status

| Item | Status | Commit(s) | Evidence |
|---|---|---|---|
| F1 Lazy-load Chat | ✅ done | `8472b68` | Re-measured: main 385.76 kB (gzip 120.57), Chat chunk 280.42 kB (gzip 86.12). |
| F2 Upload limit while reading | ✅ done | `afc388a` | Tests pass (`test_the_reader_stops_at_the_limit_and_never_holds_more`, `test_a_file_exactly_at_the_limit_is_accepted_by_the_reader`, `test_an_11_mb_streamed_upload_without_a_length_is_refused_mid_stream`); UI shows "Files can be up to 10 MB." |
| F3 Mixed doc + law | ✅ done | `2da33a8`, `54abbf4` | With documents only, the gate also scores each clause of the question (as rewritten and as asked) and keeps each candidate's best score. Probe: 0.2728 → 0.7868 and 0.3981 → 0.8731. Gold (139): recall@6 94.39% → 94.39%, abstention accuracy 96.88% → 96.88%. Verified in the app: cites Registration s.17, s.18 and the lease ¶1. |
| F4 PDF page cap (100) | ✅ done | `f0f04a5` | 100-page PDF (200 chunks): 48.1 s cold, median 38.1 s warm (CPU). 101 pages → 413, and the Chat chip shows "This PDF has 101 pages; the limit is 100." |
| F5 Cleanup | ✅ done | — | Temporary smoke-test account deleted (0 users, 0 credentials); its browser tokens cleared. |
| Multi-worker warning | ✅ done | `fa1e6cf` | `chat_documents_single_process_only` logged with `WEB_CONCURRENCY=2`. |
| Test isolation | ✅ done | `781e84c` | 267 passed with the guard on, and again with `HTTPS_PROXY/HTTP_PROXY=http://127.0.0.1:9` + `HF_HUB_OFFLINE=1`: 0 `UnmockedLLMCallError`. |
| start.sh portability | ✅ done | `d1adaea` | Starts the local `var/pgdata` cluster when Docker is absent; `.venv/Scripts`; `lsof`/`open` optional. |

## Checks at the end of the phase

ruff and `ruff format --check` clean; mypy 16 errors, all present before Chat
(0 new); pytest 267 passed; `npm run typecheck` clean; `npm run build` clean.

## Known issues / open decisions

- **Dependency pins conflict:** `docling==2.126.0` (corpus extra) needs
  `httpx>=0.28`; `litellm==1.59.12` needs `httpx<0.28`. docling is not
  imported anywhere and was not installed here. Needs a pin decision.
- A mixed question asked as one sentence with no clause break can still miss
  the statute floor (the cross-encoder's reading, not the split).
- F3 adds one rerank per clause (~3 s each on this CPU) to document questions.
- A deleted account's stale token makes the UI look signed in until a 401.
- Earlier known issues still stand (see BUILD-LOG): `--ink-3/--ink-4`
  contrast, buffered streaming, voice transcription not verified in a real
  browser.
- The smoke test drove a hidden browser pane with DOM events: behaviour was
  verified, pixel layout was not.
