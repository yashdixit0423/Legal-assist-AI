# LegalEdge Phase 1.1 — frontend brief

A build prompt for the web client. Every endpoint, field name and status code
below was read out of the running backend's OpenAPI document, not invented.
Where behaviour is unusual, the reason is given — those reasons are the product,
and a frontend that treats them as edge cases will misrepresent it.

---

## 0 · Where it lives, and what it may not do

Create the app in **`apps/web/`** inside this repository. Do not modify
anything under `apps/api/`, `cli/`, `content/`, `eval/` or `docs/`. The backend
is finished and tested (207 tests); the web client consumes it and nothing more.

**Stack:** React + TypeScript + Vite, Tailwind, shadcn/ui, React Router,
TanStack Query. No SSR, no Next.js — the backend is the only server.

**Start from the existing reference build** at
`yashdixit0423/Legal-assist-AI`, folder `legalai_frontend/`. Section 13
describes exactly what to keep from it and what must be torn out. Its visual
design is good and its component decomposition is close to right; its data
layer is entirely fictional and every byte of it has to go.

**The API base URL must be configurable** (`VITE_API_BASE_URL`, default
`http://localhost:8000`). Never hardcode a host.

---

## 1 · The one thing to understand before building anything

This product answers legal questions **only from statute text it actually
retrieved**, and refuses when the corpus does not cover the question. That
refusal is a **successful outcome**, not an error.

`POST /v1/ask` returns **HTTP 200 with `abstained: true`** when it declines.
It is not a 4xx. It is not an empty state. It is not a failure toast.

Render it as a deliberate, composed answer — the backend supplies the wording
in `answer`, which names the six Acts the corpus holds and says plainly that it
has no case law, no state amendments and no tax rates. Show `top_score` and
`score_floor` somewhere unobtrusive (a details disclosure is fine) so a curious
user can see *how far* it fell short. Do not apologise on the backend's behalf
and do not offer to "try anyway".

Equally: **every factual sentence in an answer carries a citation**, and those
citations are validated server-side against exactly the sections that were put
in the model's prompt. The citation chips are the product's credibility. They
must be prominent, and they must resolve.

---

## 2 · Authentication

JWT bearer. Only `/v1/ask` and the `/v1/credentials*` routes require it —
**everything that reads the corpus is public and must work signed out.**

| Endpoint | Body | Returns |
|---|---|---|
| `POST /v1/auth/register` | `{email, password}` (password min 12 chars) | `201` `{access_token, refresh_token, token_type, expires_in}` |
| `POST /v1/auth/login` | `{email, password}` | `200` same shape |
| `POST /v1/auth/refresh` | `{refresh_token}` | `200` same shape |
| `GET /v1/auth/me` | — | `{id, email, is_active, created_at}` |

Rules:

- Send `Authorization: Bearer <access_token>`.
- `expires_in` is seconds (default 900). Refresh **before** expiry, and refresh
  once on a 401 then retry the request exactly once. Never loop.
- A **refresh token is rejected as a bearer token** and vice versa — the server
  checks a `typ` claim. Keep them separate in your client and never substitute.
- `409 conflict` on register means the email is taken. Say so on the field.
- Login failures are **always** `401 unauthenticated` with one message,
  whether the email is unknown or the password is wrong. This is deliberate
  anti-enumeration. **Do not** write UI copy that distinguishes them — no "no
  account with that email". Show the server's message.
- There is **no logout endpoint and no revocation.** Logging out is a
  client-side discard of both tokens. Do not imply server-side session kill.

---

## 3 · `POST /v1/ask` — the main surface

### Request

```json
{
  "question": "When must a lease of immoveable property be registered?",
  "lang": "en",
  "turns": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
  "statute_slug": "registration-act-1908"
}
```

- `question`: 3–2000 chars.
- `lang`: `"en"` only. Do not offer a language picker.
- `turns`: **client-held history, max 6.** The server stores nothing. *You* own
  the conversation. If the user reloads and you kept nothing, the context is
  gone — that is the design, so persist turns in `sessionStorage` if you want
  continuity, and make clear that history is local.
- `statute_slug`: optional filter to one Act.

### Two transports, chosen by `Accept`

**Streaming** (default for the chat view) — send `Accept: text/event-stream`.
**Buffered JSON** — any other `Accept`. Same pipeline, same guarantees.

### SSE event protocol — implement all seven

| Event | Payload | What to do |
|---|---|---|
| `sources` | `{sources: [...]}` | Arrives **first, before any text.** Render the citation chips immediately — the user sees which provisions are being read before the answer starts. |
| `token` | `{text: "..."}` | Append. If `replaces_all: true` is present, **discard everything rendered and replace with this text.** |
| `citation` | `{citation_id, section_id}` | A validated citation. Activate/highlight that chip. |
| `invalidated` | `{reason, message}` | **Throw away every token rendered so far.** The model cited a section it was not given; a correction is coming as a `token` with `replaces_all`. Show a brief "correcting…" state, not an error. |
| `abstain` | `{reason, message, top_score, score_floor}` | Render the abstention (see §1). |
| `error` | `{code, message}` | Map by `code` (see §6). |
| `done` | see below | Finalise. |

`done` payload:

```json
{"answered": true, "abstained": false, "cited_section_ids": [18, 1107],
 "citation_violation": false, "model": "gpt-4.1-mini", "prompt_version": "ask-v2",
 "tokens_in": 11137, "tokens_out": 189, "latency_ms": 4973}
```

Show `tokens_in`/`tokens_out` and `model` in the UI — the user is paying for
this on their own key and spec §06 requires cost visibility. A small footer
under each answer is enough.

**The `invalidated` event is not theoretical and must be implemented.** The
server validates citations *mid-stream* and kills the stream the moment a
fabricated id appears, rather than letting it sit on screen. If you ignore this
event the user keeps reading a retracted answer — which defeats the entire
point of the product.

### Buffered response (same fields plus)

```json
{"answered": true, "abstained": false, "answer": "...", "sources": [...],
 "cited_section_ids": [18, 1107], "top_score": 0.9847, "score_floor": 0.6,
 "abstain_reason": null, "citation_violation": false, "turns_used": false,
 "rewritten_question": null, "latency_ms": 8150, ...}
```

`rewritten_question` is non-null when prior turns were folded into a standalone
question. Show it subtly ("searched for: …") so the user understands what was
actually asked.

### `sources[]` shape

```json
{"citation_id": "S1107", "section_id": 1107, "statute": "Transfer of Property Act, 1882",
 "statute_slug": "transfer-of-property-act-1882", "section_no": "107",
 "marginal_note": "leases how made.", "origin": "retrieved",
 "rerank_score": 0.9847, "cited": true}
```

- `origin` is `"retrieved"` or `"cross_reference"`. **Distinguish them
  visually.** A cross-referenced section was pulled in because the retrieved
  one points at it — often the proviso that changes the rule. Label it, e.g.
  "referenced by".
- `cited: false` means it was in the prompt but the answer did not use it. Show
  these, de-emphasised, under something like "also considered". Do not hide
  them — the set of what was *available* is part of the grounding claim.

### Citation chips

Answers contain markers like `[S1107]`, and sometimes `[S19(c)]` or
`[S18(1)(d), S1107]`. **Parse every bracketed group for `S<digits>`** — that is
exactly what the server does. Render each as an inline chip that opens the
section (§4). Never render a raw `[S1107]` as text.

Beware: statute text itself contains footnote markers like `[1]` and
`[2][State Government]`. Those are **not** citations — they have no `S` prefix.
Leave them as-is.

---

## 4 · Corpus browsing — all public, no token

| Endpoint | Use |
|---|---|
| `GET /v1/statutes` | Act list: `slug, short_title, year, jurisdiction, section_count, as_of_date, is_repealed, source_url` |
| `GET /v1/statutes/{slug}` | One Act + `sections[]` index in citation order, `sections_total`, `sections_in_force`, `parts`, `parts_available` |
| `GET /v1/statutes/{slug}/sections/{section_no}` | One section, verbatim |
| `GET /v1/sections/{section_id}` | Same by id — **this is what a citation chip resolves against** |

Things that will trip you up:

- **`parts_available` is `false` and `parts` is `[]` for every Act.** The
  Part/Chapter hierarchy is genuinely unknown — it does not exist in the source
  data. **Do not render an empty chapter tree**, and do not imply these Acts
  have no chapters. Hide the navigation entirely when `parts_available` is
  false. This is why the field exists.
- **Section numbers are not integers.** `2A`, `21-A`, `66A`, `45ZF`, `178A` are
  all real. Sort using the order the API returns (`sections[]` is already in
  legal citation order — 9 before 10, 2A after 2). **Never sort them yourself**
  as strings or numbers; you will get it wrong.
- `21A`, `21-A` and `21 a` all resolve to the same section, so URL forms are
  forgiving.
- `is_omitted: true` sections are repealed. Show them in the index, visibly
  struck through or badged "omitted", because the numbering gap looks like a
  bug otherwise. They are excluded from search by default.
- `text` is verbatim source text with footnote markers inline as `[N]`, and
  `footnotes[]` carries them. Render in a serif, generous measure, preserving
  paragraph breaks. This is the authoritative text — treat typography as a
  feature.
- `related[]` gives cross-references both ways, each with
  `direction: "outbound" | "inbound"` and `relation`. "Cites" and "cited by"
  are different things to a lawyer; label them separately.
- `explanation` is always `null` for now. Omit the section rather than showing
  an empty one.
- Always surface `as_of_date` and `source_url` on a section view. Provenance is
  not a footnote in a legal product.

---

## 5 · Search — public, no LLM, no key

`POST /v1/search` with `{q, statute_slug?, limit?, include_omitted?}`, or
`GET /v1/search?q=…` for a linkable results URL. Use the GET form for anything
the user might bookmark or share.

Hits:

```json
{"section_id": 18, "statute_slug": "registration-act-1908",
 "statute": "Registration Act, 1908", "section_no": "17",
 "marginal_note": "Documents of which registration is compulsory.",
 "snippet": "The following documents shall be registered…",
 "score": 0.03279, "dense_rank": 1, "sparse_rank": 1}
```

- `score` is a **Reciprocal Rank Fusion score, not a probability or a
  percentage.** Never render it as "97% match". Either omit it or show it as an
  opaque relevance value.
- `dense_rank` / `sparse_rank` may be `null` — a hit found only by meaning has
  no keyword rank and vice versa. Optionally show which retriever found it;
  never imply a null means zero relevance.
- `reranked: false` is returned deliberately: search skips the cross-encoder to
  stay fast. Do not promise "best match".
- Search is fast (~80 ms warm). Debounce ~250 ms and search as the user types.

---

## 6 · Errors — every one is typed, so branch on `code` and never on prose

Uniform envelope:

```json
{"error": {"code": "missing_provider_key", "message": "…", "details": {...}, "request_id": "…"}}
```

| Code | HTTP | UI response |
|---|---|---|
| `missing_provider_key` | **402** | **The most important one.** Do not show a generic failure. Route the user to Settings to add a provider key, using `details.provider` to name which one. This status exists solely so you can do that. |
| `provider_key_invalid` | 401 | Key rejected by the provider. Send to Settings, invite re-entry. |
| `provider_quota_exceeded` | 402 | Their key is out of credit. Say so plainly; it is not your bug. |
| `provider_timeout` | 504 | Offer retry. |
| `rate_limited` | 429 | Use `details.retry_after_seconds` for a countdown. See §7. |
| `unauthenticated` | 401 | Refresh once, then sign-in. |
| `not_found` | 404 | Unknown Act slug, section number or id. |
| `invalid_request` | 422 | Field-level validation; map to the form. |
| `conflict` | 409 | Email already registered. |
| `database_unavailable` / `service_unavailable` | 503 | Degraded banner, not a modal. |

Always log `request_id` to the console and show it in any error detail view —
it correlates to the server's structured logs.

---

## 7 · Rate limits

- `/v1/ask`: **20 per hour, per account.**
- `/v1/search`: **60 per minute, per IP.**
- Corpus reads: uncapped.

Responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset` (seconds). **Show remaining questions somewhere persistent**
— 20/hour is tight enough that a user will hit it, and discovering that via a
429 mid-thought is a bad experience. Disable the ask button at zero with the
reset time, rather than letting the request fail.

---

## 8 · Settings — the provider key vault

| Endpoint | Notes |
|---|---|
| `PUT /v1/credentials` `{provider, api_key}` | `provider` ∈ `anthropic, openai, google, groq, openrouter` |
| `GET /v1/credentials` | **Metadata only** |
| `DELETE /v1/credentials/{provider}` | 204 |
| `POST /v1/credentials/verify` `{provider, api_key?}` | Live-checks. Omit `api_key` to verify the stored one |

**The key is write-only and can never be read back.** `GET` returns only
`{provider, key_hint, key_version, last_verified_at, created_at, updated_at}`,
where `key_hint` is the last four characters. Design the UI around that: show
`••••••••1234`, offer Replace and Delete, and **never** a "reveal" affordance —
there is nothing to reveal.

`verify` returns **200 with `valid: false`** and a typed `error_code` when the
key is bad. It is not an HTTP error: the user asked a question about a key and
got an answer. Show a clear red/green state inline.

---

## 9 · Caching

Corpus reads send `ETag` and `Cache-Control: public, max-age=300`, and honour
`If-None-Match` with a 304. Let the browser and TanStack Query do their job;
set a 5-minute `staleTime` on statute and section queries. Never cache `/v1/ask`.

---

## 10 · Screens

1. **Ask** (`/`) — the primary surface. Question input, streamed answer with
   inline citation chips, sources panel (retrieved vs referenced, cited vs also
   considered), token/model/latency footer, remaining-questions indicator.
   Abstention rendered as a first-class answer. Local turn history with a clear
   "history is stored in this browser only" note.
2. **Browse** (`/statutes`, `/statutes/:slug`) — Act list; Act view with its
   section index in API order, omitted sections badged, no chapter tree.
3. **Section** (`/sections/:id` and `/statutes/:slug/sections/:no`) — verbatim
   text, marginal note, amendment note, footnotes, as-of date, source link,
   related sections split inbound/outbound. This is where citation chips land,
   so it must be deep-linkable and fast.
4. **Search** (`/search?q=…`) — linkable results, snippets, statute filter,
   omitted toggle.
5. **Settings** (`/settings`) — provider key vault, verify, account.
6. **Sign in / Register** (`/login`, `/register`).

Health (`GET /v1/health`) gives `corpus.retrieval_ready`. When it is `false`
the index is mid-rebuild: show a dismissible banner saying answers may be
unavailable. Do not block the UI.

---

## 11 · Non-negotiables

1. An abstention is a 200 and renders as an answer.
2. Every citation chip resolves to a real section view.
3. The `invalidated` event discards rendered text.
4. `402 missing_provider_key` routes to Settings, never a generic error.
5. No "reveal key" control anywhere.
6. Corpus browsing and search work fully signed out.
7. Never sort section numbers client-side.
8. No chapter tree while `parts_available` is false.
9. `score` is never shown as a percentage.
10. Never invent a field. If something is not in this document or the OpenAPI
    at `/docs`, it does not exist — ask rather than stub it.

---

## 12 · Verifying your work

The backend is running and serves its own interactive documentation:

```
http://localhost:8000/docs        OpenAPI UI — the authoritative contract
http://localhost:8000/v1/health   corpus counts and readiness
```

Corpus currently indexed: **6 Acts, 778 sections (665 in force), 877 chunks,
503 cross-references** — Indian Contract Act 1872, Transfer of Property Act
1882, Indian Stamp Act 1899, Registration Act 1908, Information Technology Act
2000, Digital Personal Data Protection Act 2023.

Two questions worth testing by hand, because they exercise opposite paths:

- *"When must a lease of immoveable property be registered?"* — answers, citing
  Registration Act s.17 and Transfer of Property Act s.107.
- *"What is the capital gains tax rate on a flat in Mumbai?"* — abstains, with
  no model call at all.

Every button must work against the real API. No mock data, no placeholder
handlers, no `TODO` in a click handler. If an endpoint for something does not
exist, leave the control out rather than wiring it to nothing.


---

## 13 · The reference build — what to keep, what to remove

The reference is `yashdixit0423/Legal-assist-AI`, folder `legalai_frontend/`,
generated by Builder.io from the `fusion-starter` template. Copy it into
`apps/web/` as the starting point.

### Keep — this part is good

**The visual identity.** The palette in `client/global.css` is well judged for
a legal product: warm paper background (`--background: 42 33% 97%`), deep teal
primary (`--primary: 173 43% 31%`), muted sage accent, `--radius: 0.75rem`.
Calm, readable, not a SaaS dashboard. **Keep these tokens unchanged.**

**The stack**, which already matches this brief exactly — React 18, TypeScript,
Vite, Tailwind, shadcn/ui, React Router, TanStack Query.

**The component decomposition**, which is close to right:

| Existing | Keep for |
|---|---|
| `LegalAssistLayout.tsx` | Shell, nav |
| `AskComposer.tsx` | Question input |
| `CitationChip.tsx` | Inline citation — already has a `resolving` state, which is exactly right for an async section fetch |
| `SectionReader.tsx` | Verbatim section display |
| `components/ui/*` | shadcn primitives |
| `pages/Index.tsx`, `Browse.tsx`, `Settings.tsx`, `NotFound.tsx` | Base screens |

### Remove — all of it

**`client/lib/legal-data.ts` — 167 lines of invented statute text. Delete it
entirely.** This is the single most important instruction in this document.
It hardcodes a handful of fake sections, and its fabrications are exactly the
kind this product exists to prevent:

- `related: ["Specific Relief Act, 1963 — S. 41"]` — **the Specific Relief Act
  is not in our corpus.** A citation chip pointing at it cannot resolve.
- `asOf: "31 March 2024"` — the real corpus is as-of **2026-09-10**, supplied
  per Act by the API.
- `explanation: "An agreement that stops someone…"` — the real API returns
  `explanation: null` for every section. That feature is deferred.
- `chapters: [...]` — the real API returns `parts_available: false` and an
  empty `parts` array for every Act, because the hierarchy does not exist in
  the source data.

Every one of those fields must come from the API or not be rendered. A legal
product that ships invented statute text is worse than one that ships nothing.

**`server/`, `netlify/`, `vite.config.server.ts`, `netlify.toml`, and the
`express` dependency.** The reference carries its own Express server. We have a
backend; a second one is a place for mock endpoints to hide. Remove them and
keep `vite.config.ts` only.

**`ModelSelector.tsx`.** There is no per-user model selection. The backend
reads one `LLM_MODEL` from its environment, and `GET /v1/credentials` returns
no model list — spec §06 asks for one on `verify` and it is not implemented.
A model picker would be a control wired to nothing. Remove it, and show the
model *actually used* from the `done` event's `model` field instead.

**`shared/api.ts`** — replace wholesale with a typed client generated from or
written against the real OpenAPI document at `http://localhost:8000/docs`.

### Add — missing entirely from the reference

The reference has no concept of these, and each is load-bearing:

1. **Authentication.** No login or register page exists, yet `/v1/ask`
   requires a bearer token. Add `/login` and `/register`, token storage,
   refresh-on-401, and the `typ` discipline from §2.
2. **Abstention.** Nothing in the reference models a refusal. This is the
   product's central behaviour — see §1.
3. **Streaming.** No `EventSource` or SSE handling anywhere. All seven events
   in §3 need implementing, including `invalidated`.
4. **Search.** No search page, though `GET/POST /v1/search` exists. Add
   `/search?q=…`.
5. **A section route.** Citation chips must deep-link. Add `/sections/:id`
   and `/statutes/:slug/sections/:no`.
6. **Error handling by `code`.** All ten codes in §6, especially the 402.
7. **Rate-limit display.** 20 questions/hour is tight; show what remains.

### Route map — reference → target

| Reference | Target |
|---|---|
| `/` | Keep — landing / ask entry |
| `/ask` | Keep — main ask surface |
| `/browse`, `/browse/:slug` | Keep, but drop the chapter tree |
| `/settings` | Keep — rework for the write-only vault (§8) |
| — | **add** `/search` |
| — | **add** `/sections/:id` |
| — | **add** `/login`, `/register` |

### The one-line summary

Keep the reference's *looks*. Throw away everything it *knows*. It is a
convincing shell over fabricated data, and the whole point of the backend it
is being attached to is that answers come only from text that was actually
retrieved.
