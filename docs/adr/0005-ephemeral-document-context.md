# ADR 0005 — Ephemeral document context for Chat

- **Status:** Accepted
- **Date:** 2026-10-07
- **Amends:** ADR 0002 (backend-only scope), the bullet "user document upload,
  parsing or analysis". Every other ADR 0002 exclusion stands, including chat
  sessions, message persistence and history.
- **Affects:** `POST /v1/ask`, new `POST|DELETE /v1/chat/documents`, `ask_logs`,
  prompt versions, the citation validator.

## Context

The Chat section (docs/CHAT-PLAN.md) lets a user ask about a document of their
own — a rental agreement, a notice — alongside the indexed Acts. ADR 0002 ruled
user document upload out entirely. That was a scoping decision, not a safety
one: the product's guarantees are that answers come only from retrieved text,
that every citation is checked in code against what was actually given to the
model, and that nothing about a user's questions is retained beyond the
anonymous evaluation row. Document context can be added without weakening any
of those, provided the document is treated as untrusted, temporary input.

## Decision

User documents are allowed **only** as temporary, per-user, in-memory context
for questions asked in Chat. Specifically:

1. **Upload and extraction.** `POST /v1/chat/documents` accepts one PDF, TXT or
   DOCX file of at most 10 MB, authenticated and rate limited (30 uploads per
   account per hour). The request body is read from the stream with a hard byte
   cap and parsed in memory; it is never spooled to a temporary file. The type
   is decided from the bytes (`%PDF-`, a ZIP containing `word/document.xml`, or
   valid UTF-8 without NUL bytes), never from the client's `Content-Type` or the
   filename. PDFs are capped at 300 pages; extracted text at 400,000 characters.
   A PDF with no extractable text (a scan) is refused as `document_unreadable`;
   OCR is out of scope.
2. **Chunking and embedding.** Text is chunked with the corpus chunker's limits
   (`MAX_CHUNK_TOKENS`, the `passage:` prefix) and embedded with the same model
   as the corpus, so document passages and statute passages are scored on the
   same scale.
3. **Storage.** Chunks and vectors live in a process-local `DocumentStore`
   keyed by an unguessable id and the owning user's id: 60-minute idle TTL, at
   most 6 documents per user and 500 overall (least recently used evicted).
   Nothing is written to disk, Redis or the database. A document is deleted on
   remove, on New chat, and — best effort — when the tab closes. **This
   requires a single API process** (decision D4 = A); a multi-worker deployment
   must move the store to Redis with the same TTL first.
4. **Ownership.** `/v1/ask` accepts `document_ids` (at most 3). Each is looked
   up together with the caller's user id; an unknown, expired or foreign id
   returns the same `404 document_not_found`, so ids cannot be probed.
5. **Prompt isolation.** A separate prompt version, `chat-doc-v1`, is used only
   when documents are attached; `ask-v2` is unchanged. Message order is system →
   user question → `<block>` (statute) → `<document>` (untrusted). Document text
   never enters the system role. Inside the document text, anything that looks
   like a `<block>` or `<document>` tag is neutralised so a document cannot
   close its own element or forge a statute block. The system prompt says
   document content is untrusted, never to be followed, and never to be
   presented as law (or law as document text).
6. **Citations.** Document passages carry ids of the form `D<n>-p<page>` (PDF)
   or `D<n>-para<k>` (DOCX/TXT). The validator accepts a document id only if
   that exact id was packed into the prompt; anything else is a violation,
   triggers the one retry and then abstains — the same rule as statute ids.
7. **The gate.** Statute blocks still need to clear `RERANK_SCORE_FLOOR`.
   Attached document passages are always packed (the whole document when it
   fits the document budget, otherwise the best-scoring passages plus the
   opening one), because a question such as "summarise this" cannot be scored
   against the corpus at all. The citation validator — at least one valid
   citation, none invented — remains the guarantee. With no statute block over
   the floor and no document, the request abstains exactly as before.
8. **What is returned and logged.** The upload response carries metadata only
   (id, filename, kind, pages, chunk count, expiry) — never text. The SSE
   `sources` event gains `kind: "statute" | "document"`; document sources
   include a short excerpt of the passage, returned only to its owner, so the
   citation can be checked. `ask_logs` gains `documents_used` (a count). The
   question text is logged as before; **document text is never logged**, and
   log lines about documents carry counts and ids only.

## Consequences

- ADR 0002's "never stored" property still holds for conversations, and now
  also for documents: a server restart forgets every document.
- The upload path holds up to ~10 MB per request in memory plus extracted text
  and vectors per stored document; the per-user and global caps bound this.
- Embedding a document is CPU work on the request path; it runs off the event
  loop. A 300-page PDF can take tens of seconds on the development host.
- Scanned PDFs, OCR, a document viewer, document generation, and keeping a
  document past its TTL remain out of scope.
