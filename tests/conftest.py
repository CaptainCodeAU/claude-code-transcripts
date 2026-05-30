"""Pytest configuration and fixtures for claude-code-transcripts tests."""

import contextlib
import io
import sys
from dataclasses import dataclass

import pytest


@dataclass
class Result:
    """Stand-in for click.testing.Result: exit code + combined stdout/stderr."""

    exit_code: int
    output: str


class CliRunner:
    """Signature-compatible stand-in for click.testing.CliRunner.

    Runs the package's argparse ``main(argv)`` in-process so existing tests that
    do ``CliRunner().invoke(cli, [...], input=...)`` keep working after the
    click -> argparse migration. The ``cli`` argument is accepted for
    compatibility and ignored (we always drive the package entry point). stdout
    and stderr are merged into ``Result.output`` (matching CliRunner's default).
    """

    def invoke(self, cli, args, input=None):
        from claude_code_transcripts.cli import main

        buf = io.StringIO()
        old_stdin = sys.stdin
        if input is not None:
            sys.stdin = io.StringIO(input)
        code = 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    main(list(args))
                except SystemExit as exc:
                    if isinstance(exc.code, int):
                        code = exc.code
                    elif exc.code is None:
                        code = 0
                    else:
                        code = 1
        finally:
            sys.stdin = old_stdin
        return Result(exit_code=code, output=buf.getvalue())


@pytest.fixture(autouse=True)
def mock_webbrowser_open(monkeypatch):
    """Automatically mock webbrowser.open to prevent browsers opening during tests."""
    opened_urls = []

    def mock_open(url):
        opened_urls.append(url)
        return True

    monkeypatch.setattr("claude_code_transcripts.webbrowser.open", mock_open)
    return opened_urls
