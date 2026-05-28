"""Spawn a detached background render. Stdlib only.

The session-end ``hook`` files the raw JSONL fast and then hands rendering to a
detached child so it never blocks session shutdown. ``start_new_session=True``
puts the child in its own process group so it survives the parent's exit.
"""

import subprocess
import sys


def spawn_render(jsonl_path, session_dir):
    """Start a detached `render` child and return immediately (non-blocking)."""
    cmd = [
        sys.executable,
        "-m",
        "claude_code_transcripts",
        "render",
        jsonl_path,
        "-o",
        session_dir,
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
