# ADR 0001 — Retrieval model selection

- **Status:** Accepted
- **Date:** 2026-09-10
- **Supersedes:** spec §04 stage 7, §08 ("Unchanged: … BGE-M3 …") and the
  `embedding vector(1024)` column in §06.

## Context

The Phase 1.1 plan specifies BGE-M3 for dense retrieval at 1024 dimensions, on the
grounds that it is what Phase 1 already uses. Since the plan was written,
domain-specific alternatives were evaluated and the project owner directed a change
before any code was written.

Three models were considered for the dense retriever:

| Model | Verdict |
|---|---|
| `BAAI/bge-m3` | General-purpose multilingual. Works, but knows nothing about Indian statutory language. |
| `NyayaLabs98/nyaya-embed-v1` | Fine-tuned on 27 Indian Acts plus the Constitution — the corpus we are indexing. Base model `intfloat/multilingual-e5-base`. MIT licence. |
| `law-ai/InLegalBERT` | Masked language model trained on court judgments for classification and segmentation. **No sentence-level contrastive objective.** |

And two for the reranker:

| Model | Verdict |
|---|---|
| `BAAI/bge-reranker-v2-m3` | Strongest cross-encoder available to us. |
| `NyayaLabs98/nyaya-reranker-mini-v1` | Its own model card concedes it trails `bge-reranker-v2-m3` by 6.8 points at recall@1, and argues on size. |

## Decision

1. **Dense retriever: `NyayaLabs98/nyaya-embed-v1`.** Its training corpus is our
   corpus.
2. **The embedding column is `vector(768)`,** not 1024. This lands in the first
   migration (Stage 1), because changing a vector column's dimensionality later
   means rebuilding the HNSW index and re-embedding everything.
3. **Chunks are capped at 450 tokens including the prefix.** The model's ceiling is
   512 tokens, so splitting long sections on sub-section boundaries is mandatory,
   not an optimisation. `MAX_CHUNK_TOKENS` is validated against the 512 limit in
   `Settings`.
4. **e5 prefixes are applied, and applied at the right time.** Passages are indexed
   as `passage: <act short title> — <marginal note>. <section text>` and queries are
   embedded as `query: <question>`. The passage prefix is built by the chunker at
   index time, not bolted on at query time. Both constants live in
   `app/core/config.py` and are asserted by tests.
5. **Reranker: `BAAI/bge-reranker-v2-m3`,** selected by config so the mini model can
   be swapped in if memory becomes a constraint. We are not size-constrained today.
6. **`law-ai/InLegalBERT` appears nowhere in the retrieval path.** A masked LM with
   no contrastive objective is the wrong tool for embeddings.
   `tests/unit/test_requirements_sync.py` fails if it appears in a dependency
   declaration.
7. **Every HuggingFace model is loaded at an explicit revision SHA** recorded in
   config, never a floating `main`. These are small, new repositories and their
   `main` can move under us.

## Consequences

- Retrieval quality should improve on Indian statutory phrasing relative to BGE-M3,
  and this is measurable against the Stage 9 gold set. We are not claiming the
  improvement until it is measured.
- Vectors are 25% smaller than the plan assumed (768 vs 1024 floats per chunk).
- The 512-token ceiling is stricter than BGE-M3's 8192, so the chunker carries real
  responsibility. A silently truncated passage is a silently wrong retrieval, and
  the plan's "one chunk per section" shortcut is not available to us.
- Two silent-failure modes now exist and are guarded by tests rather than by
  convention: a missing e5 prefix, and a dimension mismatch between the model and
  the column.
- `EMBED_MODEL_REVISION` and `RERANK_MODEL_REVISION` ship **empty** in Stage 0. The
  real SHAs are resolved and pinned in Stage 4, when the weights are first loaded.
  An empty revision must fail loudly at model-load time rather than silently
  resolving to `main`.
