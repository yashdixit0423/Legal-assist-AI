"""Loading the embedding model, and the two prefixes that must never diverge.

Everything that touches ``sentence-transformers`` or ``transformers`` is
imported inside the functions. The request path imports this module for
:func:`embed_query`, and an unconditional top-level ``import torch`` would put
a second and a half onto API start-up for a process that may never embed
anything.

The e5 asymmetry is the whole point of this module: passages are embedded with
``passage:`` and questions with ``query:``. Getting that wrong costs several
points of recall and raises no error anywhere, so the prefixes are applied here
and in the chunker, never by a caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.core.config import (
    EMBED_MODEL_MAX_TOKENS,
    EMBEDDING_DIM,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    ConfigError,
    Settings,
)
from app.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

logger = get_logger(__name__)

# Keyed by (repo, revision) so a revision change in the environment loads a
# different model rather than silently reusing the one already in memory.
_TOKENIZERS: dict[tuple[str, str], Any] = {}
_ENCODERS: dict[tuple[str, str], Any] = {}


class TokenCounter(Protocol):
    """Counts tokens the way the embedding model itself will."""

    def __call__(self, text: str) -> int: ...


def get_tokenizer(settings: Settings) -> Any:
    """The embedding model's own tokenizer, at the pinned revision."""
    revision = settings.require_embed_revision()
    key = (settings.EMBED_MODEL, revision)
    if key not in _TOKENIZERS:
        from transformers import AutoTokenizer

        logger.info("tokenizer_load", model=settings.EMBED_MODEL, revision=revision[:12])
        _TOKENIZERS[key] = AutoTokenizer.from_pretrained(settings.EMBED_MODEL, revision=revision)
    return _TOKENIZERS[key]


def token_counter(settings: Settings) -> TokenCounter:
    """A callable counting tokens including the special tokens the model adds.

    The ceiling we are protecting is the model's input limit, and that limit
    counts ``[CLS]`` and ``[SEP]``. Counting without them would let a chunk
    two tokens over the line through.
    """
    tokenizer = get_tokenizer(settings)

    def count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True))

    return count


def get_encoder(settings: Settings) -> Any:
    """The SentenceTransformer, on CPU, at the pinned revision.

    The three modules are assembled here rather than read from the repository's
    ``modules.json``. That file was written by sentence-transformers 5.4, and
    names its classes under ``sentence_transformers.base.modules`` — a package
    that does not exist in the 3.3.1 we pin, so ``SentenceTransformer(repo)``
    dies with ``ModuleNotFoundError: sentence_transformers.base``. Building the
    stack by hand is the fix that does not involve moving a dependency we
    pinned deliberately, and it makes the pooling explicit instead of implied:
    this is an e5 model, so it is mean pooling followed by L2 normalisation,
    and the mode is still read from the repository's own ``1_Pooling/config.json``
    rather than assumed.
    """
    revision = settings.require_embed_revision()
    key = (settings.EMBED_MODEL, revision)
    if key in _ENCODERS:
        return _ENCODERS[key]

    from sentence_transformers import SentenceTransformer, models

    logger.info("encoder_load", model=settings.EMBED_MODEL, revision=revision[:12])
    transformer = models.Transformer(
        settings.EMBED_MODEL,
        max_seq_length=EMBED_MODEL_MAX_TOKENS,
        model_args={"revision": revision},
        tokenizer_args={"revision": revision},
        config_args={"revision": revision},
    )
    pooling = _load_pooling(settings.EMBED_MODEL, revision, transformer)
    encoder = SentenceTransformer(modules=[transformer, pooling, models.Normalize()], device="cpu")
    if encoder.get_sentence_embedding_dimension() != EMBEDDING_DIM:
        msg = (
            f"{settings.EMBED_MODEL} produces "
            f"{encoder.get_sentence_embedding_dimension()} dimensions, but the "
            f"kb_chunks.embedding column is vector({EMBEDDING_DIM})"
        )
        raise ConfigError(msg)
    _ENCODERS[key] = encoder
    return encoder


def _load_pooling(repo: str, revision: str, transformer: Any) -> Any:
    """Build the Pooling module from the repository's own config.

    ``Pooling.load`` cannot read it directly: 5.x writes ``embedding_dimension``
    where 3.3.1 expects ``word_embedding_dimension``, and adds an
    ``include_prompt`` key that 3.3.1's constructor rejects outright. The
    *pooling mode* is the part that must not be guessed, so it is taken from
    the file; the rest is translated.
    """
    import json

    from huggingface_hub import hf_hub_download
    from sentence_transformers import models

    path = hf_hub_download(repo, filename="1_Pooling/config.json", revision=revision)
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    dimension = config.get("word_embedding_dimension") or config.get("embedding_dimension")
    mode = config.get("pooling_mode")
    if mode is None:
        modes = [
            name.removeprefix("pooling_mode_")
            for name, enabled in config.items()
            if name.startswith("pooling_mode_") and enabled
        ]
        if len(modes) != 1:
            msg = f"cannot determine the pooling mode of {repo} from {config!r}"
            raise ConfigError(msg)
        mode = modes[0].removesuffix("_tokens")
    return models.Pooling(
        word_embedding_dimension=dimension or transformer.get_word_embedding_dimension(),
        pooling_mode=mode,
    )


def embed_passages(settings: Settings, texts: Sequence[str]) -> list[list[float]]:
    """Embed strings that already carry the ``passage:`` prefix.

    The prefix is *not* added here. It is part of the stored chunk (see
    :mod:`app.services.kb.chunk`) because it is part of the string whose tokens
    were counted against the ceiling, and re-deriving it at embed time would
    let the two drift.
    """
    for text in texts:
        if not text.startswith(PASSAGE_PREFIX):
            msg = f"passage is missing the {PASSAGE_PREFIX!r} prefix: {text[:60]!r}"
            raise ValueError(msg)
    encoder = get_encoder(settings)
    vectors = encoder.encode(
        list(texts),
        batch_size=settings.EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [[float(value) for value in row] for row in vectors]


def embed_query(settings: Settings, question: str) -> list[float]:
    """Embed a question, applying the ``query:`` prefix here and nowhere else."""
    encoder = get_encoder(settings)
    vector = encoder.encode(
        [f"{QUERY_PREFIX}{question}"],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )[0]
    return [float(value) for value in vector]
