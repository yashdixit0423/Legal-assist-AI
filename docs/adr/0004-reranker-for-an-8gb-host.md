# ADR 0004 — The reranker on an 8 GB host

**Date:** 2026-09-11
**Status:** Accepted
**Supersedes, in part:** ADR 0001 (retrieval model selection)

## Context

ADR 0001 selected `BAAI/bge-reranker-v2-m3` over `NyayaLabs98/nyaya-reranker-mini-v1`,
on the grounds that the mini model's own card concedes it trails by 6.8 points
at recall@1 and that "we are not size-constrained". That reasoning was sound on
the evidence then available. It has since been falsified by measurement: **we
are size-constrained**, on the only machine this has ever run on.

The development host is an 8 GB M1. With Docker Desktop (1.28 GB actual, mostly
the Virtualization.framework VM), Postgres, and a desktop application resident,
usable memory sits near 2 GB and the machine is routinely several gigabytes into
swap. `bge-reranker-v2-m3` is 2.12 GB of fp32 weights.

## What was measured

Four configurations, each run against the real 139-case gold set rather than a
microbenchmark:

| Precision | Device | s/case | Projected 139 cases |
|---|---|---:|---:|
| float32 | CPU | 88 | 204 min |
| float32 | MPS | 300 | 695 min |
| float16 | MPS | 47 | 109 min |
| float16 | CPU | — | unusable: 123 s for 30 pairs in isolation |

Every one of them entered uninterruptible wait (`state=U`) with the resident
set collapsed and swap climbing past 5 GB. In isolation, on a momentarily quiet
machine, the same model does 30 pairs in 6.1 s on MPS/fp16 — a projection of
~14 minutes for the full set. The gap between 14 and 109 minutes is swap, and
it is not recoverable by tuning.

`nyaya-reranker-mini-v1` at 0.47 GB completed all 139 cases in **4 minutes 30
seconds** on CPU fp32, with no swap.

float16 is worth recording separately: on CPU it is **10× slower** than float32
(123 s vs 12.6 s for 30 pairs) because PyTorch emulates half precision there
rather than accelerating it. On MPS it is marginally faster than float32 and
halves the footprint. So `RERANK_DTYPE=float16` is only ever sensible together
with an accelerator, and the setting's docstring says so.

Scores are effectively unchanged by precision — 0.6276 (fp32/CPU), 0.6274
(fp16/CPU), 0.6279 (fp16/MPS) on the same pair. Precision was never the risk.

## Decision

1. **`nyaya-reranker-mini-v1` is the default reranker** for any host with less
   than roughly 12 GB of usable memory, and is the model the current reported
   numbers were measured with.
2. **`bge-reranker-v2-m3` remains the preferred model where memory allows**, and
   `RERANK_MODEL` / `RERANK_MODEL_REVISION` keep it one environment change away.
   ADR 0001's quality argument is not disputed; only its premise.
3. **The reported gold-set numbers must name their reranker.** recall@6 = 94.4%
   is mini's figure. bge's is unmeasured and must not be implied.
4. `RERANK_SCORE_FLOOR` is model-specific and must be recalibrated whenever the
   reranker changes. The checkpoint fingerprint covers the model, revision,
   device and dtype, so results from two rerankers can never silently blend.

## Consequences

- The shipped configuration trades ADR 0001's 6.8 points of recall@1 for a run
  that completes. On the measured evidence that trade looks better than the
  headline number suggests: mini reaches **recall@6 94.4%** and separates
  on-topic from off-topic by +0.53 against bge's +0.63.
- bge's numbers stay owed. Getting them needs a host with more memory, not more
  effort on this one — four configurations is enough to stop.
- If production targets 8 GB machines, shipping a 2.1 GB cross-encoder was
  never viable, and this ADR is the correction rather than a workaround.
