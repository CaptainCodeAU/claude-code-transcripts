"""Tests for the `hook` subcommand (SessionEnd capture pipeline)."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from claude_code_transcripts import cli, notify, spawn

CWD = "/Users/testuser/CODE/TestOwner/myproj"  # -> project "TestOwner-myproj"


@pytest.fixture
def captured(monkeypatch):
    reports = []
    spawns = []
    monkeypatch.setattr(notify, "report", lambda *a, **k: reports.append((a, k)))
    monkeypatch.setattr(spawn, "spawn_render", lambda *a, **k: spawns.append((a, k)))
    return reports, spawns


def _payload(transcript_path, cwd=CWD):
    return json.dumps(
        {
            "session_id": "sid-1",
            "transcript_path": str(transcript_path),
            "cwd": cwd,
        }
    )


def _status(reports):
    return [a[2] for a, _ in reports]


def test_hook_files_jsonl_notifies_and_spawns(tmp_path, monkeypatch, captured):
    reports, spawns = captured
    export_dir = tmp_path / "archive"
    monkeypatch.setenv("TRANSCRIPT_EXPORT_DIR", str(export_dir))
    monkeypatch.delenv("SKIP_SESSION_END_HOOK", raising=False)

    transcript = tmp_path / "sess123.jsonl"
    transcript.write_text('{"type":"user","cwd":"/x","message":{"content":"hi"}}\n')

    result = CliRunner().invoke(cli, ["hook"], input=_payload(transcript))
    assert result.exit_code == 0, result.output

    session_dir = export_dir / "TestOwner-myproj" / "sess123"
    filed = session_dir / "sess123.jsonl"
    assert filed.exists()
    assert filed.read_text() == transcript.read_text()

    assert "ok" in _status(reports)
    assert len(spawns) == 1
    (dest, sdir), _ = spawns[0]
    assert Path(dest) == filed
    assert Path(sdir) == session_dir


def test_hook_skips_unchanged_session(tmp_path, monkeypatch, captured):
    reports, spawns = captured
    export_dir = tmp_path / "archive"
    monkeypatch.setenv("TRANSCRIPT_EXPORT_DIR", str(export_dir))
    monkeypatch.delenv("SKIP_SESSION_END_HOOK", raising=False)

    transcript = tmp_path / "sess123.jsonl"
    transcript.write_text("payload\n")

    session_dir = export_dir / "TestOwner-myproj" / "sess123"
    session_dir.mkdir(parents=True)
    (session_dir / "index.html").write_text("x")
    (session_dir / "sess123.jsonl").write_text(transcript.read_text())

    result = CliRunner().invoke(cli, ["hook"], input=_payload(transcript))
    assert result.exit_code == 0
    assert "skipped" in _status(reports)
    assert spawns == []


def test_hook_opens_folder_on_skip_when_env_set(tmp_path, monkeypatch, captured):
    reports, spawns = captured
    export_dir = tmp_path / "archive"
    monkeypatch.setenv("TRANSCRIPT_EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("TRANSCRIPT_OPEN_FOLDER", "1")
    monkeypatch.delenv("SKIP_SESSION_END_HOOK", raising=False)
    opened = []
    monkeypatch.setattr(notify, "open_folder", lambda p: opened.append(p))

    transcript = tmp_path / "sess123.jsonl"
    transcript.write_text("payload\n")
    session_dir = export_dir / "TestOwner-myproj" / "sess123"
    session_dir.mkdir(parents=True)
    (session_dir / "index.html").write_text("x")
    (session_dir / "sess123.jsonl").write_text(transcript.read_text())

    result = CliRunner().invoke(cli, ["hook"], input=_payload(transcript))
    assert result.exit_code == 0
    assert "skipped" in _status(reports)
    assert opened == [str(session_dir)]


def test_hook_skip_does_not_open_folder_when_env_unset(tmp_path, monkeypatch, captured):
    reports, _ = captured
    export_dir = tmp_path / "archive"
    monkeypatch.setenv("TRANSCRIPT_EXPORT_DIR", str(export_dir))
    monkeypatch.delenv("SKIP_SESSION_END_HOOK", raising=False)
    monkeypatch.delenv("TRANSCRIPT_OPEN_FOLDER", raising=False)
    opened = []
    monkeypatch.setattr(notify, "open_folder", lambda p: opened.append(p))

    transcript = tmp_path / "sess123.jsonl"
    transcript.write_text("payload\n")
    session_dir = export_dir / "TestOwner-myproj" / "sess123"
    session_dir.mkdir(parents=True)
    (session_dir / "index.html").write_text("x")
    (session_dir / "sess123.jsonl").write_text(transcript.read_text())

    CliRunner().invoke(cli, ["hook"], input=_payload(transcript))
    assert "skipped" in _status(reports)
    assert opened == []


def test_hook_respects_skip_env(tmp_path, monkeypatch, captured):
    reports, spawns = captured
    monkeypatch.setenv("SKIP_SESSION_END_HOOK", "1")
    transcript = tmp_path / "sess123.jsonl"
    transcript.write_text("payload\n")

    result = CliRunner().invoke(cli, ["hook"], input=_payload(transcript))
    assert result.exit_code == 0
    assert reports == []
    assert spawns == []


def test_hook_missing_transcript_reports_error(tmp_path, monkeypatch, captured):
    reports, spawns = captured
    monkeypatch.delenv("SKIP_SESSION_END_HOOK", raising=False)
    result = CliRunner().invoke(cli, ["hook"], input=_payload(tmp_path / "nope.jsonl"))
    assert result.exit_code == 0
    assert "error" in _status(reports)
    assert spawns == []
