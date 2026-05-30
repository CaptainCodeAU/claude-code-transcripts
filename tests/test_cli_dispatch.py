"""Tests for the argparse dispatch layer (default subcommand, version, CliError).

These lock the behaviour that used to come from click-default-group and
click.version_option / click.ClickException.
"""

from conftest import CliRunner

from claude_code_transcripts import cli
from claude_code_transcripts.cli import (
    build_parser,
    parse_args_with_default_subcommand,
)


def _parsed(argv):
    return parse_args_with_default_subcommand(build_parser(), argv)


def test_bare_args_default_to_local():
    args = _parsed([])
    assert args.func.__name__ == "local_cmd"


def test_known_subcommand_dispatches_directly():
    args = _parsed(["all", "--dry-run"])
    assert args.func.__name__ == "all_cmd"
    assert args.dry_run is True


def test_leading_option_prepends_local():
    # `... -o foo` behaves like `... local -o foo` (DefaultGroup parity).
    args = _parsed(["-o", "/tmp/out"])
    assert args.func.__name__ == "local_cmd"
    assert args.output == "/tmp/out"


def test_version_long_flag_not_treated_as_local():
    # --version must reach the top parser (and exit 0), not become `local --version`.
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()  # prints the version


def test_version_short_flag_not_treated_as_local():
    result = CliRunner().invoke(cli, ["-v"])
    assert result.exit_code == 0


def test_json_no_json_toggle_parses():
    assert _parsed(["json", "x.jsonl", "--no-json"]).include_json is False
    assert _parsed(["json", "x.jsonl"]).include_json is True


def test_cli_error_exits_1_with_stderr_message():
    # `json` on a missing local file raises CliError -> exit 1, "Error: " message.
    result = CliRunner().invoke(cli, ["json", "/no/such/file.jsonl"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "File not found" in result.output


def test_render_missing_output_is_usage_error():
    # argparse required=True on -o exits 2 (usage error), matching click.
    result = CliRunner().invoke(cli, ["render", "x.jsonl"])
    assert result.exit_code == 2
