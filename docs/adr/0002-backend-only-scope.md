# ADR 0002 — Backend-only scope for this repository

- **Status:** Accepted
- **Date:** 2026-09-10
- **Affects:** spec §07 (frontend requirements), §09 workstream 4, §12 (`apps/web/`).

## Context

The Phase 1.1 plan describes a full product slice: four workstreams ending in a
Next.js frontend deployed behind TLS. The build brief for this repository fences the
work to the backend, and lists the frontend as a later job. The plan's §12 layout
therefore describes directories this repository must not contain.

## Decision

This repository contains the FastAPI service and the `legaledge-kb` CLI, and nothing
else. Specifically **not** built here:

- any frontend (`apps/web/`, components, hooks, `lib/api/`);
- user document upload, parsing or analysis;
- document generation, templates, DOCX/PDF export;
- chat sessions, message persistence, conversation summaries or history —
  conversation turns arrive in the request body and are never stored;
- the contradiction engine and risk flagging;
- case-law or judgment ingestion;
- any task queue (no Celery, no ARQ, no worker service) — the corpus pipeline is a
  CLI;
- object storage (no MinIO) — archived source PDFs go on a local volume;
- Kubernetes manifests.

`tests/unit/test_repo_layout.py` asserts both halves of this: the §12 directories we
do build exist, and the out-of-scope ones are absent. A future session that starts
scaffolding `apps/web/` will fail a test rather than drift.

## Consequences

- The plan's §07 and workstream 4 are not deliverables here. The API is designed so
  that a frontend can be added later without changing it: SSE for `/v1/ask`, stable
  machine-readable error codes (notably `missing_provider_key`, so a client can route
  the user to Settings), and citation ids that resolve through `GET /v1/sections/{id}`.
- Caddy is still configured in the production overlay, because the API itself needs
  TLS termination. Its only upstream is `api`.
- Compose has two required services (`postgres`, `api`) plus two optional ones
  (`redis`, `langfuse`), against the plan's four-container `web`-inclusive figure.
