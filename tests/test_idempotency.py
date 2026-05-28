"""Tests for the session-export idempotency skip-check (core/idempotency.py)."""

from claude_code_transcripts.core.idempotency import should_skip


def _setup(tmp_path, source_bytes, exported_bytes, *, index=True, exported=True):
    uuid = "abc123"
    src = tmp_path / "src.jsonl"
    src.write_bytes(source_bytes)
    session_dir = tmp_path / "proj" / uuid
    session_dir.mkdir(parents=True)
    if index:
        (session_dir / "index.html").write_text("<html></html>")
    if exported:
        (session_dir / f"{uuid}.jsonl").write_bytes(exported_bytes)
    return str(src), str(session_dir), uuid


def test_skips_when_index_and_jsonl_present_and_sizes_equal(tmp_path):
    src, session_dir, uuid = _setup(tmp_path, b"x" * 100, b"x" * 100)
    assert should_skip(src, session_dir, uuid) is True


def test_does_not_skip_when_source_larger(tmp_path):
    src, session_dir, uuid = _setup(tmp_path, b"x" * 200, b"x" * 100)
    assert should_skip(src, session_dir, uuid) is False


def test_does_not_skip_when_index_missing(tmp_path):
    src, session_dir, uuid = _setup(tmp_path, b"x" * 100, b"x" * 100, index=False)
    assert should_skip(src, session_dir, uuid) is False


def test_does_not_skip_when_exported_jsonl_missing(tmp_path):
    src, session_dir, uuid = _setup(tmp_path, b"x" * 100, b"", exported=False)
    assert should_skip(src, session_dir, uuid) is False


def test_does_not_skip_when_source_missing(tmp_path):
    _, session_dir, uuid = _setup(tmp_path, b"x" * 100, b"x" * 100)
    assert should_skip(str(tmp_path / "gone.jsonl"), session_dir, uuid) is False
