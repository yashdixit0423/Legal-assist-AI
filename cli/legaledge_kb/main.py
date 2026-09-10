"""Typer entry point.

Only commands that are actually implemented are registered. Pipeline
subcommands (fetch, parse, chunk, embed, explain, verify, stats) are added in
the stage that implements them, so ``--help`` never advertises a no-op.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from app import __version__
from app.core.config import ConfigError, get_settings
from app.core.errors import CorpusError
from app.db.models import KbChunk, Statute
from app.db.session import sync_session
from app.services.kb.ingest import fetch_act, parse_act
from app.services.kb.manifest import ActEntry, load_manifest, select_acts

app = typer.Typer(
    name="legaledge-kb",
    help="LegalEdge corpus pipeline: acquire, parse, index and explain Indian statutes.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _acts(tier: int | None, slug: str | None) -> list[ActEntry]:
    return select_acts(load_manifest(), tier=tier, slug=slug)


TierOption = Annotated[int | None, typer.Option("--tier", help="Ingest one manifest tier.")]
SlugOption = Annotated[str | None, typer.Option("--act", help="Ingest one Act by slug.")]


@app.command()
def fetch(
    tier: TierOption = None,
    slug: SlugOption = None,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Re-download even if archived.")
    ] = False,
) -> None:
    """Archive Acts from India Code, with checksums and an ingest_runs row."""
    settings = get_settings()
    entries = _acts(tier, slug)
    table = Table("act", "items", "sha256", "source", title="Fetched")
    with sync_session(settings) as session:
        for entry in entries:
            result = fetch_act(settings, entry, session=session, refresh=refresh)
            table.add_row(
                entry.slug,
                str(result.items),
                result.sha256[:16] + "...",
                "cache" if result.from_cache else "portal",
            )
    console.print(table)


@app.command()
def parse(
    tier: TierOption = None,
    slug: SlugOption = None,
    lenient: Annotated[
        bool, typer.Option("--lenient", help="Write rows despite verification errors.")
    ] = False,
) -> None:
    """Parse archived Acts into the database, verifying before writing."""
    settings = get_settings()
    entries = _acts(tier, slug)
    failed = False
    table = Table("act", "sections", "warnings", "errors", title="Parsed")
    with sync_session(settings) as session:
        for entry in entries:
            try:
                result = parse_act(settings, entry, session, strict=not lenient)
            except CorpusError as exc:
                failed = True
                table.add_row(entry.slug, "-", "-", f"[red]{exc}[/red]")
                continue
            failed = failed or not result.report.ok
            table.add_row(
                entry.slug,
                str(result.sections_written),
                str(len(result.report.warnings)),
                str(len(result.report.errors)),
            )
            for warning in result.report.warnings:
                console.print(f"  [yellow]{warning['kind']}[/yellow]: {warning['detail']}")
    console.print(table)
    if failed:
        console.print("[red]verification failed[/red]")
        raise typer.Exit(code=1)


@app.command()
def stats() -> None:
    """Corpus size and freshness."""
    settings = get_settings()
    with sync_session(settings) as session:
        rows = session.execute(
            select(
                Statute.slug, Statute.section_count, Statute.as_of_date, Statute.source_sha256
            ).order_by(Statute.year)
        ).all()
        chunks = session.execute(select(func.count()).select_from(KbChunk)).scalar_one()
    table = Table("act", "sections", "as of", "source sha256", title="Corpus")
    for slug, count, as_of, sha in rows:
        table.add_row(slug, str(count), str(as_of), (sha or "")[:16] + "...")
    console.print(table)
    console.print(f"acts: {len(rows)}  chunks: {chunks}")


@app.command()
def version() -> None:
    """Print the package version."""
    console.print(__version__)


@app.command("check-config")
def check_config() -> None:
    """Validate the environment and print the effective configuration.

    Secrets are shown as set/unset, never printed. Exits non-zero when the
    environment cannot produce valid settings.
    """
    try:
        settings = get_settings()
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    secret_fields = {"JWT_SECRET", "CREDENTIAL_ENC_KEY", "LANGFUSE_SECRET_KEY", "SENTRY_DSN"}
    table = Table("setting", "value", title="Effective configuration")
    for name in sorted(type(settings).model_fields):
        value = getattr(settings, name)
        if name in secret_fields:
            table.add_row(name, "[dim]set[/dim]" if value else "[yellow]unset[/yellow]")
        else:
            table.add_row(name, str(value))
    console.print(table)
    console.print("[green]configuration valid[/green]")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
