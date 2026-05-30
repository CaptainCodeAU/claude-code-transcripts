"""Zero-dependency fence for the stdlib core layer.

The session-capture hot path imports ``claude_code_transcripts.core.*`` (and a
future stdlib-only plugin shim will too). Those imports must never drag in a
third-party dependency. Because importing a submodule runs the package
``__init__`` first, this also asserts the package shim stays dep-free on import.

Each case runs in a fresh subprocess so the check sees a clean ``sys.modules``.
"""

import subprocess
import sys

import pytest

FORBIDDEN = ("jinja2", "markdown", "httpx", "click", "questionary")

CORE_MODULES = (
    "claude_code_transcripts.core.naming",
    "claude_code_transcripts.core.resolve",
    "claude_code_transcripts.core.idempotency",
)


def _third_party_after_import(module):
    """Import ``module`` in a subprocess; return the forbidden deps it pulled in."""
    code = (
        "import sys; "
        f"import {module}; "
        "forbidden = {'jinja2', 'markdown', 'httpx', 'click', 'questionary'}; "
        "print(','.join(sorted(forbidden & set(sys.modules))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [m for m in result.stdout.strip().split(",") if m]


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_import_pulls_no_third_party(module):
    pulled = _third_party_after_import(module)
    assert not pulled, f"importing {module} pulled third-party deps: {pulled}"


# Layer isolation: render owns jinja2 + markdown only; click/questionary belong
# strictly to the cli layer, httpx strictly to fetch. Importing any render
# submodule must not drag click/questionary/httpx in.
RENDER_MODULES = (
    "claude_code_transcripts.render.env",
    "claude_code_transcripts.render.assets",
    "claude_code_transcripts.render.markdown_ext",
    "claude_code_transcripts.render.blocks",
    "claude_code_transcripts.render.gist",
    "claude_code_transcripts.render.indexes",
    "claude_code_transcripts.render.html",
)
RENDER_FORBIDDEN = {"click", "questionary", "httpx"}


@pytest.mark.parametrize("module", RENDER_MODULES)
def test_render_import_pulls_no_cli_or_fetch_deps(module):
    pulled = _third_party_after_import(module)
    leaked = RENDER_FORBIDDEN & set(pulled)
    assert not leaked, f"importing {module} leaked layer deps: {sorted(leaked)}"


def test_picker_is_stdlib_only():
    """The interactive picker (questionary replacement) must stay dependency-free."""
    pulled = _third_party_after_import("claude_code_transcripts.picker")
    assert not pulled, f"importing picker pulled third-party deps: {pulled}"


def test_detector_catches_a_deps_carrying_module():
    """Sanity check: the fence really would fail for the cli module (pulls click)."""
    pulled = _third_party_after_import("claude_code_transcripts.cli")
    assert "click" in pulled
