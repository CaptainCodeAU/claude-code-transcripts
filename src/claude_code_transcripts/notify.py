"""Desktop / voice / log notifications for the capture pipeline. Stdlib only.

Ported from the personal plugin, but with NO personal defaults: voice
notification is opt-in via the ``TRANSCRIPT_VOICE_URL`` (and optional
``TRANSCRIPT_VOICE_ID``) environment variables and is skipped entirely when
they are unset, so nothing setup-specific lives in this public repo.
"""

import datetime
import json
import os
import subprocess
import sys

IS_MACOS = sys.platform == "darwin"
LOG_FILE = os.path.expanduser("~/.claude/logs/transcript-export.log")


def notify_desktop(title, message):
    """Best-effort desktop notification (macOS osascript / Linux notify-send)."""
    try:
        if IS_MACOS:
            escaped_msg = message.replace('"', '\\"')
            escaped_title = title.replace('"', '\\"')
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'display notification "{escaped_msg}" with title "{escaped_title}"',
                ]
            )
        else:
            subprocess.Popen(["notify-send", title, message])
    except OSError:
        pass


def notify_voice(message):
    """Best-effort voice notification. Opt-in via TRANSCRIPT_VOICE_URL."""
    url = os.environ.get("TRANSCRIPT_VOICE_URL")
    if not url:
        return
    payload = {"message": message, "voice_enabled": True}
    voice_id = os.environ.get("TRANSCRIPT_VOICE_ID")
    if voice_id:
        payload["voice_id"] = voice_id
    try:
        subprocess.Popen(
            [
                "curl",
                "-s",
                "--connect-timeout",
                "2",
                "-X",
                "POST",
                url,
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps(payload),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def log_entry(
    session_id,
    project,
    status,
    error="",
    duration_ms=0,
    source="",
    cwd="",
    log_file=None,
):
    """Append one JSONL record describing an export attempt."""
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": session_id,
        "project": project,
        "status": status,
        "duration_ms": duration_ms,
    }
    if error:
        entry["error"] = error
    if source:
        entry["source"] = source
    if cwd:
        entry["cwd"] = cwd
    path = log_file or LOG_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def report(session_id, project, status, error="", duration_ms=0, source="", cwd=""):
    """Log the attempt and surface it via desktop + voice notifications."""
    log_entry(session_id, project, status, error, duration_ms, source, cwd)
    if status == "ok":
        notify_desktop("Claude Transcripts", f"Session exported -> {project}")
        notify_voice(f"Transcript exported to {project}")
    elif status == "skipped":
        notify_desktop("Claude Transcripts", f"Session already exported -> {project}")
    else:
        reason = error or "unknown error"
        notify_desktop("Claude Transcripts", f"Export failed: {reason}")
        notify_voice(f"Transcript export failed. {reason}")
