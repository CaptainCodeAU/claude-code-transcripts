"""Convert Claude Code session JSON to clean, mobile-friendly HTML pages.

This package is layered so the session-capture hot path stays dependency-light:

- ``core``           stdlib only (naming, jsonl, summary, archive, github,
                     analysis, resolve, idempotency)
- ``notify`` / ``spawn``  stdlib-only capture helpers
- ``render``         jinja2 + markdown  (lazy)
- ``fetch``          httpx + keychain   (lazy)
- ``cli``            stdlib argparse + stdlib picker (lazy; still imports httpx)

Importing this package, or any ``core`` submodule, pulls in **zero** third-party
dependencies. Everything that does carry a dependency is re-exported lazily via
the PEP 562 module ``__getattr__`` below, so ``import
claude_code_transcripts.core.naming`` never drags in jinja2/markdown/httpx.
"""

import importlib
import tempfile  # noqa: F401  (live attr: tests patch claude_code_transcripts.tempfile)
import webbrowser  # noqa: F401  (live attr: conftest patches claude_code_transcripts.webbrowser)

# --- eager stdlib core re-exports (zero third-party) ---
from .core.naming import get_project_display_name
from .core.jsonl import (
    extract_text_from_content,
    parse_session_file,
    _parse_jsonl_file,
    is_json_like,
    is_task_notification,
)
from .core.summary import (
    get_session_summary,
    _get_jsonl_summary,
    find_local_sessions,
)
from .core.archive import find_all_sessions
from .core.resolve import resolve_project_name
from .core.idempotency import should_skip
from .core.github import (
    detect_github_repo,
    extract_repo_from_session,
    enrich_sessions_with_repos,
    filter_sessions_by_repo,
)
from .core.analysis import (
    analyze_conversation,
    format_tool_stats,
    is_tool_result_message,
    COMMIT_PATTERN,
)
from . import notify, spawn

# Public deps-carrying symbols -> the submodule that defines each one. Resolved
# on first access by ``__getattr__``; importing ``core`` never triggers these.
_LAZY_SYMBOLS = {
    # render (jinja2 + markdown)
    "get_macros": "render.env",
    "get_template": "render.env",
    "CSS": "render.assets",
    "JS": "render.assets",
    "render_markdown_text": "render.markdown_ext",
    "format_json": "render.blocks",
    "render_todo_write": "render.blocks",
    "render_write_tool": "render.blocks",
    "render_edit_tool": "render.blocks",
    "render_bash_tool": "render.blocks",
    "render_content_block": "render.blocks",
    "render_user_message_content": "render.blocks",
    "render_assistant_message": "render.blocks",
    "render_message": "render.blocks",
    "make_msg_id": "render.blocks",
    "inject_gist_preview_js": "render.gist",
    "GIST_PREVIEW_JS": "render.gist",
    "_generate_project_index": "render.indexes",
    "_generate_master_index": "render.indexes",
    "generate_html": "render.html",
    "generate_html_from_session_data": "render.html",
    "generate_batch_html": "render.html",
    "generate_pagination_html": "render.html",
    "generate_index_pagination_html": "render.html",
    # fetch (httpx + keychain)
    "CredentialsError": "fetch.credentials",
    "get_access_token_from_keychain": "fetch.credentials",
    "get_org_uuid_from_config": "fetch.credentials",
    "API_BASE_URL": "fetch.api",
    "ANTHROPIC_VERSION": "fetch.api",
    "get_api_headers": "fetch.api",
    "fetch_sessions": "fetch.api",
    "fetch_session": "fetch.api",
    "_fetch_teleport_events": "fetch.api",
    "format_session_for_display": "fetch.api",
    # cli (stdlib argparse + stdlib picker)
    "cli": "cli",
    "main": "cli",
    "create_gist": "cli",
    "resolve_credentials": "cli",
    "is_url": "cli",
    "fetch_url_to_tempfile": "cli",
}


def __getattr__(name):
    """Lazily import and cache deps-carrying symbols (PEP 562)."""
    if name == "httpx":
        # Live attribute so monkeypatch.setattr("...httpx.get") resolves; the
        # fetch/cli layers call httpx.get on this same module object.
        import httpx

        globals()["httpx"] = httpx
        return httpx
    if name == "_macros":
        from .render.env import get_macros

        value = get_macros()
        globals()["_macros"] = value
        return value
    target = _LAZY_SYMBOLS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{target}", __name__)
    value = getattr(module, name)
    # Cache as a real attribute. For ``cli`` this also overwrites the submodule
    # binding the import machinery set, so the attribute is the entry-point callable.
    globals()[name] = value
    return value
