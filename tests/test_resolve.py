"""Tests for cwd-first project-name resolution (core/resolve.py)."""

import json

from claude_code_transcripts.core.resolve import (
    cwd_to_project_key,
    extract_cwd_from_jsonl,
    resolve_project_name,
)


class TestCwdToProjectKey:
    def test_replaces_slashes_underscores_dots(self):
        assert (
            cwd_to_project_key("/Users/alice/CODE/MyOrg/my_project.x")
            == "-Users-alice-CODE-MyOrg-my-project-x"
        )

    def test_matches_claude_code_lossy_encoding(self):
        # _ and . both collapse to - (lossy, same as Claude Code)
        assert cwd_to_project_key("/a/b_c.d") == "-a-b-c-d"


class TestExtractCwdFromJsonl:
    def test_returns_first_nonempty_cwd(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps({"type": "user"})
            + "\n"
            + json.dumps({"type": "user", "cwd": "/Users/alice/CODE/Org/proj"})
            + "\n"
        )
        assert extract_cwd_from_jsonl(str(f)) == "/Users/alice/CODE/Org/proj"

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_cwd_from_jsonl(str(tmp_path / "nope.jsonl")) == ""


class TestResolveProjectName:
    def test_payload_cwd_takes_priority(self, tmp_path):
        name, source = resolve_project_name(
            str(tmp_path / "x.jsonl"),
            payload_cwd="/Users/alice/CODE/TestOwner/claude-code-transcripts",
        )
        # "code" inside the project name must be preserved (the original bug)
        assert name == "TestOwner-claude-code-transcripts"
        assert source == "payload_cwd"

    def test_falls_back_to_jsonl_cwd(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            json.dumps({"type": "user", "cwd": "/home/bob/repos/Org/app"}) + "\n"
        )
        name, source = resolve_project_name(str(f), payload_cwd="")
        assert name == "Org-app"
        assert source == "jsonl_cwd"

    def test_falls_back_to_encoded_folder_name(self, tmp_path):
        # No payload cwd and an empty JSONL -> use the parent dir's encoded name
        proj = tmp_path / "-Users-alice-CODE-Org-thing"
        proj.mkdir()
        f = proj / "s.jsonl"
        f.write_text("")
        name, source = resolve_project_name(str(f), payload_cwd="")
        assert name == "Org-thing"
        assert source == "transcript_path"

    def test_unresolved_fallback(self):
        name, source = resolve_project_name("", payload_cwd="")
        assert name == "_unresolved"
        assert source == "unresolved"

    def test_cwd_first_converges_with_encoded_for_normal_paths(self, tmp_path):
        # Resolving from the real cwd and from the encoded folder name should
        # produce the same display name for a normal path.
        cwd = "/Users/alice/CODE/TestOwner/claude-code-transcripts"
        from_cwd, _ = resolve_project_name(str(tmp_path / "x.jsonl"), payload_cwd=cwd)

        proj = tmp_path / cwd_to_project_key(cwd)
        proj.mkdir()
        f = proj / "x.jsonl"
        f.write_text("")
        from_encoded, _ = resolve_project_name(str(f), payload_cwd="")

        assert from_cwd == from_encoded == "TestOwner-claude-code-transcripts"
