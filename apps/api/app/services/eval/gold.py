"""The gold set, and the metrics that make the retrieval claim checkable.

Spec §10 calls the gold set "the real deliverable", and the reason is that
every other number in this build is a number about the build. Recall against
hand-labelled sections is a number about whether the thing works.

Two rules keep it honest:

* **Labels are verified before anything is scored.** A gold entry naming a
  section the corpus does not hold is a defect in the gold set, not a retrieval
  miss, and scoring it as a miss would quietly understate recall forever. The
  runner refuses to produce metrics until every label resolves.
* **The adversarial half is scored on abstention, not on retrieval.** For an
  out-of-corpus question there is no right section; the only correct behaviour
  is to refuse, and that is what gets measured.

No LLM is called anywhere in this module. Retrieval quality and abstention
accuracy are properties of the index and the gate, and measuring them must not
depend on a provider key being present.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import CorpusError
from app.core.logging import get_logger
from app.db.models import Statute, StatuteSection
from app.services.kb.crossref import normalise_section_no
from app.services.kb.embedding import release_encoder
from app.services.retrieval.hybrid import hybrid_search
from app.services.retrieval.rerank import rerank

logger = get_logger(__name__)

DEFAULT_GOLD = Path("eval/gold/gold-v1.json")
RECALL_AT = (1, 3, 6, 10, 20)
CHECKPOINT_DIR = Path("eval/gold/.checkpoints")


@dataclass(frozen=True)
class GoldCase:
    """One labelled question."""

    id: str
    question: str
    topic: str
    expected_section_ids: frozenset[int]
    must_abstain: bool

    @property
    def is_adversarial(self) -> bool:
        return self.must_abstain


@dataclass
class CaseOutcome:
    """What retrieval did with one gold case.

    ``scored`` is the cross-encoder's full output in rank order, as
    ``(section_id, score)`` pairs with chunk-level duplicates preserved — that
    is what the abstention gate actually sees. Keeping it is what makes score
    floor tuning free: the floor is a post-filter over these numbers, so trying
    a different one is a re-read of a JSON file rather than an hour of
    recomputation. It is the reason the floor is *not* part of the checkpoint
    fingerprint.
    """

    case: GoldCase
    scored: list[tuple[int, float]]
    latency_ms: int
    floor: float
    top_n: int

    @property
    def ranked_section_ids(self) -> list[int]:
        """Distinct sections, best first."""
        seen: list[int] = []
        for section_id, _ in self.scored:
            if section_id not in seen:
                seen.append(section_id)
        return seen

    @property
    def top_score(self) -> float | None:
        return self.scored[0][1] if self.scored else None

    @property
    def abstained(self) -> bool:
        """Recomputed from the cached scores, never stored.

        Identical to what ``apply_floor`` decides at request time: nothing in
        the best ``top_n`` chunks clears the floor.
        """
        return not any(score >= self.floor for _, score in self.scored[: self.top_n])

    def refloor(self, *, floor: float, top_n: int | None = None) -> CaseOutcome:
        """The same measurement, judged against a different floor. No compute."""
        return CaseOutcome(
            case=self.case,
            scored=self.scored,
            latency_ms=self.latency_ms,
            floor=floor,
            top_n=top_n if top_n is not None else self.top_n,
        )

    def hit_at(self, k: int) -> bool:
        """True when any labelled section appears in the first ``k`` results."""
        if not self.case.expected_section_ids:
            return False
        return bool(self.case.expected_section_ids & set(self.ranked_section_ids[:k]))

    @property
    def reciprocal_rank(self) -> float:
        for index, section_id in enumerate(self.ranked_section_ids, start=1):
            if section_id in self.case.expected_section_ids:
                return 1.0 / index
        return 0.0

    @property
    def correct(self) -> bool:
        """Adversarial cases are correct when refused; labelled ones when found."""
        if self.case.must_abstain:
            return self.abstained
        return self.hit_at(6) and not self.abstained


@dataclass
class Report:
    """The whole run."""

    outcomes: list[CaseOutcome] = field(default_factory=list)
    label_errors: list[str] = field(default_factory=list)

    @property
    def in_corpus(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if not o.case.is_adversarial]

    @property
    def adversarial(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if o.case.is_adversarial]

    def recall_at(self, k: int) -> float:
        cases = self.in_corpus
        if not cases:
            return 0.0
        return sum(1 for o in cases if o.hit_at(k)) / len(cases)

    @property
    def mrr(self) -> float:
        cases = self.in_corpus
        if not cases:
            return 0.0
        return sum(o.reciprocal_rank for o in cases) / len(cases)

    @property
    def abstention_accuracy(self) -> float:
        """Share of out-of-corpus questions correctly refused."""
        cases = self.adversarial
        if not cases:
            return 0.0
        return sum(1 for o in cases if o.abstained) / len(cases)

    @property
    def false_abstention_rate(self) -> float:
        """Share of answerable questions wrongly refused — the cost of the floor."""
        cases = self.in_corpus
        if not cases:
            return 0.0
        return sum(1 for o in cases if o.abstained) / len(cases)

    @property
    def latency_p50(self) -> int:
        return self._percentile(50)

    @property
    def latency_p95(self) -> int:
        return self._percentile(95)

    def refloor(self, *, floor: float, top_n: int | None = None) -> Report:
        """This run re-judged at a different floor, in microseconds.

        Tuning the floor is the whole reason Pass A caches scores rather than
        verdicts. Sweeping ten candidate floors used to mean ten full runs.
        """
        return Report(
            outcomes=[o.refloor(floor=floor, top_n=top_n) for o in self.outcomes],
            label_errors=list(self.label_errors),
        )

    def _percentile(self, pct: int) -> int:
        values = sorted(o.latency_ms for o in self.outcomes)
        if not values:
            return 0
        index = min(len(values) - 1, int(round((pct / 100) * (len(values) - 1))))
        return values[index]


async def load_gold(session: AsyncSession, path: Path = DEFAULT_GOLD) -> list[GoldCase]:
    """Read the gold file and resolve every label to a real section id.

    Raises :class:`CorpusError` naming every unresolvable label. Failing loudly
    here is the point: a silently dropped label inflates recall.
    """
    if not path.exists():
        raise CorpusError(f"Gold set not found at {path}.")
    doc = json.loads(path.read_text(encoding="utf-8"))
    index = await _section_index(session)

    cases: list[GoldCase] = []
    problems: list[str] = []
    for raw in doc.get("in_corpus", []) + doc.get("adversarial", []):
        ids: set[int] = set()
        for group in raw.get("expected", []):
            slug = group["statute_slug"]
            for number in group["sections"]:
                key = (slug, normalise_section_no(number))
                section_id = index.get(key)
                if section_id is None:
                    problems.append(f"{raw['id']}: {slug} has no section {number!r}")
                    continue
                ids.add(section_id)
        cases.append(
            GoldCase(
                id=raw["id"],
                question=raw["question"],
                topic=raw.get("topic", ""),
                expected_section_ids=frozenset(ids),
                must_abstain=bool(raw.get("must_abstain", False)),
            )
        )
    if problems:
        raise CorpusError(
            "The gold set names sections that are not in the corpus:\n  " + "\n  ".join(problems)
        )
    return cases


async def _section_index(session: AsyncSession) -> dict[tuple[str, str], int]:
    rows = (
        await session.execute(
            select(Statute.slug, StatuteSection.section_no, StatuteSection.id).join(
                StatuteSection, StatuteSection.statute_id == Statute.id
            )
        )
    ).all()
    return {(str(slug), normalise_section_no(str(number))): int(sid) for slug, number, sid in rows}


async def retrieve_candidates(
    session: AsyncSession, settings: Settings, case: GoldCase
) -> tuple[list[Any], int]:
    """Phase 1: hybrid retrieval only. Needs the embedder, not the reranker."""
    started = time.perf_counter()
    candidates = await hybrid_search(session, settings, case.question)
    return candidates, int((time.perf_counter() - started) * 1000)


def score_candidates(
    settings: Settings, case: GoldCase, candidates: list[Any], retrieval_ms: int
) -> CaseOutcome:
    """Phase 2: cross-encoder scoring. Needs the reranker, not the embedder."""
    started = time.perf_counter()
    ranked = rerank(settings, case.question, candidates)
    elapsed = retrieval_ms + int((time.perf_counter() - started) * 1000)
    return CaseOutcome(
        case=case,
        scored=[(item.candidate.section_id, item.score) for item in ranked],
        latency_ms=elapsed,
        floor=settings.RERANK_SCORE_FLOOR,
        top_n=settings.RERANK_TOP_N,
    )


async def run_case(session: AsyncSession, settings: Settings, case: GoldCase) -> CaseOutcome:
    """Retrieve and score one case — the same path ``/v1/ask`` takes."""
    candidates, retrieval_ms = await retrieve_candidates(session, settings, case)
    return score_candidates(settings, case, candidates, retrieval_ms)


def stratified_sample(cases: list[GoldCase], size: int) -> list[GoldCase]:
    """A subset that keeps the shape of the set, for iteration not reporting.

    Proportional across topic groups and across the labelled/adversarial split,
    so a sample cannot accidentally drop every adversarial question or every
    question about one Act. Deterministic: the same size always yields the same
    subset, because a moving sample makes two runs incomparable.
    """
    if size >= len(cases):
        return cases
    groups: dict[tuple[bool, str], list[GoldCase]] = {}
    for case in cases:
        groups.setdefault((case.must_abstain, case.topic), []).append(case)

    picked: list[GoldCase] = []
    share = size / len(cases)
    for key in sorted(groups, key=lambda k: (k[0], k[1])):
        members = sorted(groups[key], key=lambda c: c.id)
        picked.extend(members[: max(1, round(len(members) * share))])
    picked.sort(key=lambda c: c.id)
    return picked[:size]


def fingerprint(settings: Settings, gold_path: Path) -> str:
    """Identify the exact configuration a set of results was measured under.

    Every input that can move a score goes in: the gold file itself, the torch
    device, both model revisions, and the candidate counts.

    ``RERANK_SCORE_FLOOR`` and ``RERANK_TOP_N`` deliberately do **not**, because
    they do not move a score — they only decide what a score means. They are
    applied when the report is assembled, so sweeping a floor costs a re-read
    of the ledger instead of an hour of recomputation.
    Results measured under different values are not comparable — mixing CPU and
    MPS scores in one recall figure means two instruments behind one number,
    and a case sitting near the floor could flip for reasons that have nothing
    to do with retrieval. The fingerprint is in the checkpoint *filename*, so a
    changed configuration simply starts a new file instead of silently
    resuming into the old one.
    """
    material = json.dumps(
        {
            "gold": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
            "device": settings.resolve_device(),
            "embed": f"{settings.EMBED_MODEL}@{settings.EMBED_MODEL_REVISION}",
            "rerank": f"{settings.RERANK_MODEL}@{settings.RERANK_MODEL_REVISION}",
            "top_k": settings.RETRIEVAL_TOP_K,
            "candidates": settings.RERANK_CANDIDATES,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def checkpoint_path(settings: Settings, gold_path: Path) -> Path:
    return CHECKPOINT_DIR / f"{gold_path.stem}-{fingerprint(settings, gold_path)}.jsonl"


def _read_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    """Completed cases, keyed by id. A truncated final line is discarded."""
    if not path.exists():
        return {}
    done: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("checkpoint_partial_line_discarded")
            continue
        done[row["id"]] = row
    return done


def _append_checkpoint(path: Path, outcome: CaseOutcome) -> None:
    """Write one result and flush, so a kill costs one case and not the run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": outcome.case.id,
        # Scores, not verdicts. A verdict bakes in one floor; scores let any
        # floor be evaluated later for nothing.
        "scored": [[sid, round(score, 6)] for sid, score in outcome.scored],
        "latency_ms": outcome.latency_ms,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
        handle.flush()


def _outcome_from_row(case: GoldCase, row: dict[str, Any], settings: Settings) -> CaseOutcome:
    return CaseOutcome(
        case=case,
        scored=[(int(sid), float(score)) for sid, score in row["scored"]],
        latency_ms=int(row["latency_ms"]),
        floor=settings.RERANK_SCORE_FLOOR,
        top_n=settings.RERANK_TOP_N,
    )


async def run_gold(
    session: AsyncSession,
    settings: Settings,
    *,
    path: Path = DEFAULT_GOLD,
    limit: int | None = None,
    sample: int | None = None,
    fresh: bool = False,
) -> Report:
    """Run the gold set in two phases, resuming from a checkpoint.

    **All retrieval happens first, then the embedder is released, then
    everything is scored.** That ordering is the memory fix. The embedder is
    ~1.1 GB and the cross-encoder ~2.1 GB; holding both on an 8 GB host that is
    also running Docker is what turned an earlier run into swap death — the
    process sat in uninterruptible wait with a 4 MB resident set, making no
    progress at all. Interleaving them per case, which is what the request path
    does and what this function used to do, keeps both resident throughout.
    """
    cases = await load_gold(session, path)
    if sample is not None:
        cases = stratified_sample(cases, sample)
    if limit is not None:
        cases = cases[:limit]

    ledger = checkpoint_path(settings, path)
    if fresh and ledger.exists():
        ledger.unlink()
    done = _read_checkpoint(ledger)
    if done:
        logger.info("gold_resuming", completed=len(done), of=len(cases))

    outstanding = [c for c in cases if c.id not in done]

    retrieved: dict[str, tuple[list[Any], int]] = {}
    for number, case in enumerate(outstanding, start=1):
        retrieved[case.id] = await retrieve_candidates(session, settings, case)
        if number % 25 == 0:
            logger.info("gold_retrieved", done=number, of=len(outstanding))

    if outstanding:
        release_encoder(settings)

    for number, case in enumerate(outstanding, start=1):
        candidates, retrieval_ms = retrieved.pop(case.id)
        _append_checkpoint(ledger, score_candidates(settings, case, candidates, retrieval_ms))
        if number % 5 == 0:
            logger.info("gold_scored", done=number, of=len(outstanding))

    # Assembled from the ledger, so a resumed run and a fresh one agree exactly.
    rows = _read_checkpoint(ledger)
    by_id = {c.id: c for c in cases}
    report = Report()
    for case_id, row in rows.items():
        case = by_id.get(case_id)
        if case is not None:
            report.outcomes.append(_outcome_from_row(case, row, settings))
    report.outcomes.sort(key=lambda o: o.case.id)
    return report


def to_dict(report: Report) -> dict[str, Any]:
    """A JSON-serialisable summary, for storing a run alongside a commit."""
    return {
        "cases": len(report.outcomes),
        "in_corpus": len(report.in_corpus),
        "adversarial": len(report.adversarial),
        "recall": {f"@{k}": round(report.recall_at(k), 4) for k in RECALL_AT},
        "mrr": round(report.mrr, 4),
        "abstention_accuracy": round(report.abstention_accuracy, 4),
        "false_abstention_rate": round(report.false_abstention_rate, 4),
        "latency_ms": {"p50": report.latency_p50, "p95": report.latency_p95},
        "misses": [
            {
                "id": o.case.id,
                "topic": o.case.topic,
                "question": o.case.question,
                "abstained": o.abstained,
                "top_score": o.top_score,
                "rank_of_first_correct": _rank_of(o),
            }
            for o in report.in_corpus
            if not o.correct
        ],
        "wrongly_answered": [
            {
                "id": o.case.id,
                "topic": o.case.topic,
                "question": o.case.question,
                "top_score": o.top_score,
            }
            for o in report.adversarial
            if not o.abstained
        ],
    }


def _rank_of(outcome: CaseOutcome) -> int | None:
    for index, section_id in enumerate(outcome.ranked_section_ids, start=1):
        if section_id in outcome.case.expected_section_ids:
            return index
    return None
