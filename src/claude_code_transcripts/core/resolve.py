"""Cwd-first project-name resolution. Stdlib only.

Prefer the lossless ``cwd`` (from the SessionEnd payload or the JSONL) over the
lossy ``~/.claude/projects`` encoded folder name, because Claude Code collapses
``/``, ``_``, and ``.`` all into ``-`` (so the encoded name is ambiguous). Every
branch funnels through the single, fixed ``get_project_display_name``.
"""

import json
import pathlib

from .naming import get_project_display_name


def cwd_to_project_key(cwd):
    """Encode an absolute cwd the same lossy way Claude Code does."""
    return cwd.replace("/", "-").replace("_", "-").replace(".", "-")


def extract_cwd_from_jsonl(transcript_path):
    """Return the first non-empty ``cwd`` field in the JSONL, or ""."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = entry.get("cwd", "")
                if cwd:
                    return cwd
    except OSError:
        pass
    return ""


def resolve_project_name(transcript_path, payload_cwd=""):
    """Resolve the archive project name, cwd-first.

    Returns ``(display_name, source_label)``. Fallback order:
    1. payload ``cwd`` (lossless)       -> "payload_cwd"
    2. JSONL ``cwd`` field (lossless)   -> "jsonl_cwd"
    3. encoded ~/.claude/projects name  -> "transcript_path"
    4. ``("_unresolved", "unresolved")``
    """
    if payload_cwd:
        return get_project_display_name(cwd_to_project_key(payload_cwd)), "payload_cwd"

    jsonl_cwd = extract_cwd_from_jsonl(transcript_path) if transcript_path else ""
    if jsonl_cwd:
        return get_project_display_name(cwd_to_project_key(jsonl_cwd)), "jsonl_cwd"

    if transcript_path:
        parent_name = pathlib.Path(transcript_path).parent.name
        if parent_name and parent_name not in (".", "/"):
            return get_project_display_name(parent_name), "transcript_path"

    return "_unresolved", "unresolved"
