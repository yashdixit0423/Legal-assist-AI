# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 — builder: compile wheels into a virtualenv we can copy wholesale.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build-time only: compilers and postgres headers for asyncpg/psycopg/argon2.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Requirements first so the dependency layer survives source edits.
COPY requirements/api.txt /tmp/requirements/api.txt
RUN pip install --requirement /tmp/requirements/api.txt

# The corpus pipeline is an opt-in build arg: docling + ocrmypdf + datasets are
# ~1.5 GB and the request path never imports them.
ARG INSTALL_CORPUS=false
COPY requirements/corpus.txt /tmp/requirements/corpus.txt
RUN if [ "$INSTALL_CORPUS" = "true" ]; then \
        pip install --requirement /tmp/requirements/corpus.txt; \
    fi

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY cli ./cli
RUN pip install --no-deps .

# ---------------------------------------------------------------------------
# Stage 2 — runtime: no compilers, non-root, only the libraries we need.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/models \
    TOKENIZERS_PARALLELISM=false

# System packages per the plan: OCR (English + Hindi), PDF tooling, libpq.
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-hin \
        ghostscript \
        qpdf \
        poppler-utils \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 legaledge \
    && useradd --system --uid 1001 --gid legaledge --create-home legaledge

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv/legaledge
COPY --chown=legaledge:legaledge pyproject.toml README.md alembic.ini ./
COPY --chown=legaledge:legaledge apps ./apps
COPY --chown=legaledge:legaledge cli ./cli
COPY --chown=legaledge:legaledge content ./content
COPY --chown=legaledge:legaledge scripts ./scripts

# Model cache and the source-document archive are volumes, owned by the app user.
RUN mkdir -p /models /srv/legaledge/var/corpus_archive \
    && chown -R legaledge:legaledge /models /srv/legaledge/var

USER legaledge
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/v1/health >/dev/null || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
