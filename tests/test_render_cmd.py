"""Tests for the `render` subcommand (the background hook child)."""

from conftest import CliRunner

from claude_code_transcripts import cli, notify

SAMPLE = (
    '{"type":"user","timestamp":"2026-01-01T00:00:00Z",'
    '"message":{"role":"user","content":"hello world"}}\n'
    '{"type":"assistant","timestamp":"2026-01-01T00:00:01Z",'
    '"message":{"role":"assistant","content":[{"type":"text","text":"hi there"}]}}\n'
)


def test_render_produces_index_html(tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text(SAMPLE)
    out = tmp_path / "proj" / "sess"

    result = CliRunner().invoke(cli, ["render", str(jsonl), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert (out / "index.html").exists()


def test_render_requires_output(tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text(SAMPLE)
    result = CliRunner().invoke(cli, ["render", str(jsonl)])
    assert result.exit_code != 0  # -o/--output is required


def test_render_opens_folder_when_env_set(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(notify, "open_folder", lambda p: opened.append(p))
    monkeypatch.setenv("TRANSCRIPT_OPEN_FOLDER", "1")

    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text(SAMPLE)
    out = tmp_path / "proj" / "sess"
    result = CliRunner().invoke(cli, ["render", str(jsonl), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert opened == [str(out.resolve())]


def test_render_does_not_open_folder_when_env_unset(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(notify, "open_folder", lambda p: opened.append(p))
    monkeypatch.delenv("TRANSCRIPT_OPEN_FOLDER", raising=False)

    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text(SAMPLE)
    out = tmp_path / "proj" / "sess"
    result = CliRunner().invoke(cli, ["render", str(jsonl), "-o", str(out)])

    assert result.exit_code == 0
    assert opened == []
