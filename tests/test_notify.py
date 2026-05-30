"""Tests for notify.py (desktop / voice / log)."""

import json
import subprocess

import pytest

from claude_code_transcripts import notify


class FakePopen:
    calls = []

    def __init__(self, args, **kwargs):
        FakePopen.calls.append((args, kwargs))


@pytest.fixture(autouse=True)
def fake_popen(monkeypatch):
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    return FakePopen


def test_notify_desktop_macos_uses_osascript(monkeypatch, fake_popen):
    monkeypatch.setattr(notify, "IS_MACOS", True)
    notify.notify_desktop("Title", "Hello")
    assert len(fake_popen.calls) == 1
    args, _ = fake_popen.calls[0]
    assert args[0] == "osascript"
    assert "Hello" in args[2]


def test_notify_voice_skips_without_url(monkeypatch, fake_popen):
    monkeypatch.delenv("TRANSCRIPT_VOICE_URL", raising=False)
    notify.notify_voice("hi")
    assert fake_popen.calls == []


def test_notify_voice_posts_when_configured(monkeypatch, fake_popen):
    monkeypatch.setenv("TRANSCRIPT_VOICE_URL", "http://localhost:9999/notify")
    monkeypatch.setenv("TRANSCRIPT_VOICE_ID", "vid")
    notify.notify_voice("hello there")
    assert len(fake_popen.calls) == 1
    args, _ = fake_popen.calls[0]
    assert args[0] == "curl"
    assert "http://localhost:9999/notify" in args
    payload = json.loads(args[-1])
    assert payload["message"] == "hello there"
    assert payload["voice_id"] == "vid"


def test_log_entry_writes_jsonl(tmp_path):
    log = tmp_path / "log.jsonl"
    notify.log_entry(
        "sid", "Proj", "ok", duration_ms=12, source="payload_cwd", log_file=str(log)
    )
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session_id"] == "sid"
    assert rec["project"] == "Proj"
    assert rec["status"] == "ok"
    assert rec["duration_ms"] == 12
    assert rec["source"] == "payload_cwd"


def test_report_ok_notifies_exported(monkeypatch, fake_popen, tmp_path):
    monkeypatch.setattr(notify, "IS_MACOS", True)
    monkeypatch.setattr(notify, "LOG_FILE", str(tmp_path / "l.jsonl"))
    monkeypatch.delenv("TRANSCRIPT_VOICE_URL", raising=False)
    notify.report("sid", "Proj", "ok")
    osascripts = [c for c in fake_popen.calls if c[0][0] == "osascript"]
    assert any("exported" in c[0][2] for c in osascripts)


def test_report_error_notifies_failure(monkeypatch, fake_popen, tmp_path):
    monkeypatch.setattr(notify, "IS_MACOS", True)
    monkeypatch.setattr(notify, "LOG_FILE", str(tmp_path / "l.jsonl"))
    monkeypatch.delenv("TRANSCRIPT_VOICE_URL", raising=False)
    notify.report("sid", "Proj", "error", error="boom")
    osascripts = [c for c in fake_popen.calls if c[0][0] == "osascript"]
    assert any("failed" in c[0][2].lower() for c in osascripts)


# ---- open_folder ----


def test_open_folder_macos_uses_open(monkeypatch, fake_popen, tmp_path):
    monkeypatch.setattr(notify, "IS_MACOS", True)
    notify.open_folder(str(tmp_path))
    assert len(fake_popen.calls) == 1
    args, _ = fake_popen.calls[0]
    assert args == ["open", str(tmp_path)]


def test_open_folder_linux_uses_xdg_open(monkeypatch, fake_popen, tmp_path):
    monkeypatch.setattr(notify, "IS_MACOS", False)
    notify.open_folder(str(tmp_path))
    assert len(fake_popen.calls) == 1
    args, _ = fake_popen.calls[0]
    assert args == ["xdg-open", str(tmp_path)]


def test_open_folder_swallows_oserror(monkeypatch, tmp_path):
    def boom(*a, **kw):
        raise OSError("no such command")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(notify, "IS_MACOS", True)
    # Must not raise.
    notify.open_folder(str(tmp_path))
