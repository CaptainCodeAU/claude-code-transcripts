"""Tests for spawn.py (detached background render)."""

import subprocess
import sys

from claude_code_transcripts import spawn


def test_spawn_render_is_detached(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    spawn.spawn_render("/x/abc.jsonl", "/out/abc")

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == sys.executable
    assert args[1] == "-m"
    assert "claude_code_transcripts" in args
    assert "render" in args
    assert "/x/abc.jsonl" in args
    assert args[-2:] == ["-o", "/out/abc"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["close_fds"] is True
