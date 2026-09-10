"""The CLI must not advertise commands it cannot perform."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from app import __version__
from legaledge_kb.main import app as cli_app

runner = CliRunner()

# Pipeline verbs land in the stage that implements them (spec §08, task 1.2).
UNIMPLEMENTED_VERBS = ("fetch", "parse", "chunk", "embed", "explain", "verify", "stats")


def test_version_command(settings_env):
    result = runner.invoke(cli_app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_check_config_reports_valid_environment(settings_env):
    result = runner.invoke(cli_app, ["check-config"])
    assert result.exit_code == 0
    assert "configuration valid" in result.stdout


def test_check_config_never_prints_secret_values(settings_env):
    result = runner.invoke(cli_app, ["check-config"])
    assert "AAAAAAAA" not in result.stdout
    assert "test-only-secret-value" not in result.stdout


def test_check_config_exits_non_zero_on_bad_environment(settings_env):
    settings_env.setattr("app.core.config._ENV_FILE", None)
    settings_env.delenv("DATABASE_URL")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    result = runner.invoke(cli_app, ["check-config"])
    assert result.exit_code == 1
    assert "DATABASE_URL" in result.stdout


@pytest.mark.parametrize("verb", UNIMPLEMENTED_VERBS)
def test_no_placeholder_pipeline_commands_are_registered(settings_env, verb):
    """A command that exists but does nothing is worse than a missing one."""
    result = runner.invoke(cli_app, [verb])
    assert result.exit_code != 0, f"{verb} is registered but not implemented yet"


def test_registered_commands_are_exactly_the_implemented_ones():
    """Asserted against the Typer object, not the rendered help (terminal width)."""
    registered = {
        command.name or (command.callback.__name__ if command.callback else "?")
        for command in cli_app.registered_commands
    }
    assert registered == {"version", "check-config"}
