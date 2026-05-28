"""Tests for the `render` subcommand (the background hook child)."""

from click.testing import CliRunner

from claude_code_transcripts import cli

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
