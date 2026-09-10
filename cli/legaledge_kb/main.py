"""Typer entry point.

Only commands that are actually implemented are registered. Pipeline
subcommands (fetch, parse, chunk, embed, explain, verify, stats) are added in
the stage that implements them, so ``--help`` never advertises a no-op.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from app import __version__
from app.core.config import ConfigError, get_settings

app = typer.Typer(
    name="legaledge-kb",
    help="LegalEdge corpus pipeline: acquire, parse, index and explain Indian statutes.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


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
