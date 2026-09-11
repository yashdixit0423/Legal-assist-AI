# Frontend workplan — self-directed build prompt

**Target:** `legalai_frontend/` (in place, where the owner put it).
**Backend:** live at `http://localhost:8000`, 6 Acts / 778 sections / 877
embedded chunks, `retrieval_ready: true`.
**Contract:** `docs/FRONTEND-BRIEF.md` is authoritative. This file is the
order of work and the acceptance bar.

---

## The rule that governs every decision

Nothing renders that did not come from the API. No placeholder statute text,
no invented section, no mock latency, no simulated stream. If an endpoint for
something does not exist, the control does not exist. The backend's whole
claim is that answers come only from retrieved text; a frontend that fakes
any part of that is worse than no frontend.

Corollary: **delete before adding.** Every mock must be gone before the
feature that replaces it is written, so there is never a moment where a
component can silently fall back to fiction.

---

## Phase 0 — strip the fiction

1. Delete `client/lib/legal-data.ts` (167 lines of invented statutes,
   including a cross-reference to the Specific Relief Act, which is not in
   the corpus).
2. Delete `server/`, `netlify/`, `vite.config.server.ts`, `netlify.toml`,
   and the `express` + `dotenv` dependencies. The backend is the server.
3. Delete `client/components/ModelSelector.tsx`,
   `client/hooks/use-model-configurations.ts`, `client/lib/model-config.ts`.
   There is no per-user model selection: the backend reads one `LLM_MODEL`
   and exposes no model list. Show the model actually used, from `done.model`.
4. Delete `builder.config.json`, `AGENTS.md` (generator artefacts).
5. `.env.example` with `VITE_API_BASE_URL=http://localhost:8000`.

**Done when** `grep -rE "legal-data|mockAnswer|answerBeforeCitation" client/`
returns nothing and the app fails to compile — that failure is the proof the
fiction is load-bearing nowhere.

## Phase 1 — the API layer

`client/lib/api/` — types transcribed from the live OpenAPI, not guessed.

- `types.ts` — `AskResponse`, `SourceBlock`, `SectionDetail`, `StatuteSummary`,
  `StatuteDetail`, `SearchHit`, `TokenResponse`, `CredentialResponse`,
  `ApiError`.
- `client.ts` — fetch wrapper: base URL from env, bearer injection, parses the
  `{error:{code,message,details,request_id}}` envelope into a typed
  `ApiError`, refresh-once-on-401 then retry once (never loop), surfaces
  `X-RateLimit-*`.
- `ask.ts` — SSE via `fetch` + `ReadableStream` (**not** `EventSource`, which
  cannot send an `Authorization` header or a POST body). Parses all seven
  events. `invalidated` clears accumulated text; `token.replaces_all` replaces
  it.
- `auth.ts` — register / login / refresh / me, token storage, `typ` separation.

**Done when** a scratch call against the live API returns real statutes.

## Phase 2 — screens, in dependency order

1. **Auth** (`/login`, `/register`) — nothing else works signed in without it.
2. **Section reader** (`/sections/:id`, `/statutes/:slug/sections/:no`) —
   citation chips need somewhere to land, so this comes before Ask.
3. **Browse** (`/browse`, `/browse/:slug`) — real Acts, section index in API
   order, omitted badged, **no chapter tree** (`parts_available` is false).
4. **Ask** (`/`, `/ask`) — the main surface. Real SSE, real abstention, real
   sources, token/model/latency footer, rate-limit indicator.
5. **Search** (`/search?q=…`) — new, linkable.
6. **Settings** (`/settings`) — write-only vault, verify, account.

## Phase 3 — the behaviours that are the product

- Abstention renders as a composed answer at HTTP 200, never an error.
- `invalidated` discards rendered text and shows a correcting state.
- `402 missing_provider_key` routes to Settings naming `details.provider`.
- Citation parsing handles `[S1107]`, `[S19(c)]`, `[S18(1)(d), S1107]`;
  leaves `[1]` and `[2][State Government]` alone.
- Section numbers never sorted client-side.
- `score` never shown as a percentage.
- Rate limit visible before it bites.

---

## Acceptance — each verified against the running backend, not asserted

| # | Check |
|---|---|
| 1 | `GET /v1/statutes` renders six real Acts with real as-of dates |
| 2 | An Act page lists sections in citation order with `2A` after `2`, `9` before `10` |
| 3 | A section page shows verbatim text, footnotes, source URL, inbound/outbound related |
| 4 | "When must a lease of immoveable property be registered?" streams an answer citing Registration s.17 and TPA s.107 |
| 5 | Every citation chip in that answer opens the right section |
| 6 | "What is the capital gains tax rate on a flat in Mumbai?" renders an abstention at 200 |
| 7 | Search for "restraint of trade" returns Contract s.27 first |
| 8 | Signed out, browse and search work; Ask prompts sign-in |
| 9 | With no provider key, Ask on an in-corpus question routes to Settings via 402 |
| 10 | `npm run typecheck` clean, `npm run build` succeeds |

## Non-goals

No chat persistence server-side (turns stay in `sessionStorage`; the backend
stores nothing and the brief forbids adding it). No document upload. No
document generation. No Hindi. No model picker.
