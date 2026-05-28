"""Back-compat contract fence.

This locks the public import surface of ``claude_code_transcripts`` so the
upcoming package split cannot silently break callers (the test suite, the
``reconcile_sessions.py`` / ``migrate_project.py`` scripts, and the
``pyproject.toml`` console-script entry point).

It must pass BEFORE the refactor (on the monolith) and stay green through every
step of it. Each name below is imported by a test, a script, or the entry point;
see the import headers of tests/test_generate_html.py and tests/test_all.py.
"""

import importlib

import pytest

# Symbols that must be importable from the top-level package.
PUBLIC_SYMBOLS = [
    # core (stdlib) -- imported by tests and the standalone scripts
    "get_project_display_name",
    "get_session_summary",
    "find_local_sessions",
    "find_all_sessions",
    "parse_session_file",
    "detect_github_repo",
    "extract_repo_from_session",
    "enrich_sessions_with_repos",
    "filter_sessions_by_repo",
    "analyze_conversation",
    "format_tool_stats",
    "is_tool_result_message",
    "is_json_like",
    # render (jinja2/markdown) -- imported by tests
    "generate_html",
    "generate_batch_html",
    "render_markdown_text",
    "format_json",
    "render_todo_write",
    "render_write_tool",
    "render_edit_tool",
    "render_bash_tool",
    "render_content_block",
    "render_user_message_content",
    "inject_gist_preview_js",
    "create_gist",
    "GIST_PREVIEW_JS",
    "_generate_project_index",
    "_generate_master_index",
    "_macros",
    # fetch (httpx/keychain) -- imported by tests
    "format_session_for_display",
    # cli + entry point
    "cli",
    "main",
]

# Attributes that tests monkeypatch as ``claude_code_transcripts.<mod>.<fn>``.
# These must remain live attributes of the package module after the split.
PATCHABLE_MODULE_ATTRS = [
    ("webbrowser", "open"),  # tests/conftest.py autouse fixture
    ("httpx", "get"),  # tests/test_all.py
    ("tempfile", "gettempdir"),  # tests/test_generate_html.py
]


@pytest.fixture(scope="module")
def pkg():
    return importlib.import_module("claude_code_transcripts")


@pytest.mark.parametrize("name", PUBLIC_SYMBOLS)
def test_public_symbol_importable(pkg, name):
    assert hasattr(pkg, name), f"claude_code_transcripts.{name} is missing"


@pytest.mark.parametrize("mod,attr", PATCHABLE_MODULE_ATTRS)
def test_patchable_module_attr_resolves(pkg, mod, attr):
    module = getattr(pkg, mod, None)
    assert module is not None, f"claude_code_transcripts.{mod} must be a live attribute"
    assert hasattr(module, attr), f"claude_code_transcripts.{mod}.{attr} must resolve"


def test_github_repo_attr_is_settable(pkg):
    # tests/test_generate_html.py reads and writes this module global.
    original = getattr(pkg, "_github_repo", "__missing__")
    assert original != "__missing__", "claude_code_transcripts._github_repo must exist"
    try:
        pkg._github_repo = "owner/repo"
        assert pkg._github_repo == "owner/repo"
    finally:
        pkg._github_repo = None if original == "__missing__" else original
