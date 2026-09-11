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
from app.services.answer.abstain import apply_floor
from app.services.kb.crossref import normalise_section_no
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
    """What the pipeline did with one gold case."""

    case: GoldCase
    ranked_section_ids: list[int]
    top_score: float | None
    abstained: bool
    latency_ms: int

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


async def run_case(session: AsyncSession, settings: Settings, case: GoldCase) -> CaseOutcome:
    """Retrieve, rerank and apply the gate — exactly as ``/v1/ask`` does."""
    started = time.perf_counter()
    candidates = await hybrid_search(session, settings, case.question)
    ranked = rerank(settings, case.question, candidates)
    gate = apply_floor(ranked, floor=settings.RERANK_SCORE_FLOOR, top_n=settings.RERANK_TOP_N)

    seen: list[int] = []
    for item in ranked:
        section_id = item.candidate.section_id
        if section_id not in seen:
            seen.append(section_id)
    return CaseOutcome(
        case=case,
        ranked_section_ids=seen,
        top_score=gate.top_score,
        abstained=not gate.passed,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def fingerprint(settings: Settings, gold_path: Path) -> str:
    """Identify the exact configuration a set of results was measured under.

    Every input that can move a score goes in: the gold file itself, the torch
    device, both model revisions, the score floor and the candidate count.
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
            "floor": settings.RERANK_SCORE_FLOOR,
            "top_k": settings.RETRIEVAL_TOP_K,
            "top_n": settings.RERANK_TOP_N,
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
        "ranked_section_ids": outcome.ranked_section_ids,
        "top_score": outcome.top_score,
        "abstained": outcome.abstained,
        "latency_ms": outcome.latency_ms,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
        handle.flush()


def _outcome_from_row(case: GoldCase, row: dict[str, Any]) -> CaseOutcome:
    return CaseOutcome(
        case=case,
        ranked_section_ids=list(row["ranked_section_ids"]),
        top_score=row["top_score"],
        abstained=bool(row["abstained"]),
        latency_ms=int(row["latency_ms"]),
    )


async def run_gold(
    session: AsyncSession,
    settings: Settings,
    *,
    path: Path = DEFAULT_GOLD,
    limit: int | None = None,
    fresh: bool = False,
) -> Report:
    """Run the gold set, resuming from a checkpoint of the same configuration.

    Each case is written to the checkpoint as it completes, so an interrupted
    run resumes where it stopped. This matters because a full run takes over an
    hour on CPU, and losing all of it to a stray Ctrl-C is a bad trade for the
    forty lines this costs.
    """
    cases = await load_gold(session, path)
    if limit is not None:
        cases = cases[:limit]

    ledger = checkpoint_path(settings, path)
    if fresh and ledger.exists():
        ledger.unlink()
    done = _read_checkpoint(ledger)
    if done:
        logger.info("gold_resuming", completed=len(done), of=len(cases), checkpoint=str(ledger))

    report = Report()
    for number, case in enumerate(cases, start=1):
        if case.id in done:
            report.outcomes.append(_outcome_from_row(case, done[case.id]))
            continue
        outcome = await run_case(session, settings, case)
        _append_checkpoint(ledger, outcome)
        report.outcomes.append(outcome)
        if number % 5 == 0:
            logger.info("gold_progress", done=number, of=len(cases))
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
