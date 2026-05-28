"""Session-export idempotency check. Stdlib only.

A session is considered already-exported (skip) when its rendered ``index.html``
and the archived ``<uuid>.jsonl`` both exist AND the archived JSONL is the same
size as the source transcript. JSONL is append-only, so equal size means the
session is unchanged since the last export.
"""

import os


def should_skip(transcript_path, session_dir, uuid):
    """Return True if the session is already exported and unchanged."""
    index = os.path.join(session_dir, "index.html")
    exported_jsonl = os.path.join(session_dir, uuid + ".jsonl")
    try:
        if os.path.isfile(index) and os.path.isfile(exported_jsonl):
            return os.path.getsize(transcript_path) == os.path.getsize(exported_jsonl)
    except OSError:
        return False
    return False
