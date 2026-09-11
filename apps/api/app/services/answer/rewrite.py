"""Query rewriting — spec §05 step 1.

"and the notice period?" is not a question you can retrieve against. When the
request carries prior turns, they are folded into a standalone question before
retrieval runs.

Two properties matter more than the rewrite quality:

* **It is skipped on a first question.** No turns, no rewrite, no model call,
  no latency. Most questions are first questions.
* **It fails open.** A rewrite that errors, times out, or comes back empty
  leaves the original question in place. Rewriting is an optimisation; losing
  it must never turn a working question into a failed request. In particular a
  missing provider key must not 402 here — the abstention path downstream is
  allowed to answer without a key at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import LegalEdgeError
from app.core.logging import get_logger
from app.services.llm import client as llm

logger = get_logger(__name__)

REWRITE_PROMPT_VERSION = "rewrite-v1"

SYSTEM_PROMPT = """\
You rewrite a follow-up question into a standalone one, using the conversation \
that came before it.

Rules:
- Output the rewritten question and nothing else. No preamble, no quotes, no \
explanation.
- Resolve pronouns and elliptical references ("it", "that section", "and the \
notice period?") into explicit terms drawn from the earlier turns.
- Keep the user's meaning exactly. Do not answer the question, do not add legal \
analysis, and do not introduce any statute, section number or fact that does \
not appear in the conversation.
- If the question already stands alone, return it unchanged.
- Keep it to one sentence.\
"""

# A rewrite longer than this is the model explaining itself rather than
# rewriting, and is discarded.
MAX_REWRITE_CHARS = 400


@dataclass(frozen=True)
class Rewrite:
    """What retrieval should actually search for."""

    question: str
    original: str
    rewritten: bool
    reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.rewritten and self.question.strip() != self.original.strip()


def _render_turns(turns: list[dict[str, str]]) -> str:
    return "\n".join(f"{turn['role']}: {turn['content']}" for turn in turns)


async def rewrite_question(
    settings: Settings, question: str, turns: list[dict[str, str]]
) -> Rewrite:
    """Fold prior turns into a standalone question, or return the original."""
    if not turns:
        return Rewrite(question=question, original=question, rewritten=False, reason="no_turns")
    if not settings.REWRITE_ENABLED:
        return Rewrite(question=question, original=question, rewritten=False, reason="disabled")

    prompt = f"Conversation so far:\n{_render_turns(turns)}\n\nFollow-up question: {question}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    try:
        completion = await llm.complete(
            settings,
            messages,
            model=settings.rewrite_model,
            max_tokens=settings.REWRITE_MAX_TOKENS,
            timeout_seconds=settings.REWRITE_TIMEOUT_SECONDS,
        )
    except LegalEdgeError as exc:
        # Includes a missing key: rewriting must not be the thing that turns an
        # answerable-by-abstention request into a 402.
        logger.warning("rewrite_failed", code=exc.code)
        return Rewrite(
            question=question, original=question, rewritten=False, reason=f"failed_{exc.code}"
        )

    candidate = completion.text.strip().strip('"')
    if not candidate or len(candidate) > MAX_REWRITE_CHARS:
        logger.warning("rewrite_discarded", length=len(candidate))
        return Rewrite(
            question=question, original=question, rewritten=False, reason="unusable_output"
        )

    logger.info("rewritten", original_len=len(question), rewritten_len=len(candidate))
    return Rewrite(question=candidate, original=question, rewritten=True)
