"""Tests for scripts/reconcile_sessions.py"""

import sys
import time
from pathlib import Path

import pytest

# Add scripts/ to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from unittest.mock import patch

from reconcile_sessions import (
    UNKNOWN_PROJECT,
    UUID_PATTERN,
    Category,
    MoveResult,
    PlannedMove,
    ReconciliationReport,
    _human_size,
    _relative_age,
    categorize_all,
    extract_last_timestamp,
    categorize_folder,
    compare_session_copies,
    compute_move_plan,
    cwd_to_project_name,
    extract_cwd_from_jsonl,
    extract_project_from_html,
    find_matching_project,
    find_uuid_folders,
    format_category_table,
    format_delete_plan,
    format_move_plan,
    format_report,
    list_existing_projects,
    main,
    move_to_delete_folder,
    parse_args,
    process_category_a,
    process_category_b,
    resolve_target_project,
    scan_archive_for_projects,
)

# --- Phase 1: CLI + UUID detection ---


class TestParseArgs:
    def test_with_path(self):
        args = parse_args(["/some/path"])
        assert args.path == "/some/path"
        assert args.dry_run is False
        assert args.no_reindex is False
        assert args.yes is False

    def test_dry_run(self):
        args = parse_args(["--dry-run", "/some/path"])
        assert args.dry_run is True

    def test_no_reindex(self):
        args = parse_args(["--no-reindex", "/some/path"])
        assert args.no_reindex is True

    def test_yes_flag(self):
        args = parse_args(["--yes", "/some/path"])
        assert args.yes is True

    def test_verbose_flag(self):
        args = parse_args(["--verbose", "/some/path"])
        assert args.verbose is True

    def test_verbose_short_flag(self):
        args = parse_args(["-v", "/some/path"])
        assert args.verbose is True

    def test_cleanup_flag(self):
        args = parse_args(["--cleanup", "/some/path"])
        assert args.cleanup is True

    def test_no_path_exits(self):
        with pytest.raises(SystemExit):
            parse_args([])


class TestUUIDPattern:
    def test_matches_valid_uuid(self):
        assert UUID_PATTERN.match("f1a2a7f0-5057-43c9-8e59-163d2c2ceb92")

    def test_rejects_non_uuid(self):
        assert not UUID_PATTERN.match("CaptainCodeAU-My-Project")
        assert not UUID_PATTERN.match("_legacy_something")
        assert not UUID_PATTERN.match("")

    def test_rejects_partial_uuid(self):
        assert not UUID_PATTERN.match("f1a2a7f0-5057-43c9-8e59")


class TestFindUUIDFolders:
    def test_detects_uuid_dirs(self, tmp_path):
        uuid1 = tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92"
        uuid2 = tmp_path / "00759c27-1653-4a26-a6c3-a5d7db3c2161"
        uuid1.mkdir()
        uuid2.mkdir()
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        result = find_uuid_folders(tmp_path)
        assert len(result) == 2
        assert all(UUID_PATTERN.match(p.name) for p in result)

    def test_ignores_files(self, tmp_path):
        (tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92").write_text("file")
        result = find_uuid_folders(tmp_path)
        assert len(result) == 0

    def test_ignores_symlinks(self, tmp_path):
        real = tmp_path / "real_dir"
        real.mkdir()
        link = tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92"
        link.symlink_to(real)
        result = find_uuid_folders(tmp_path)
        assert len(result) == 0

    def test_returns_sorted(self, tmp_path):
        (tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92").mkdir()
        (tmp_path / "00759c27-1653-4a26-a6c3-a5d7db3c2161").mkdir()
        result = find_uuid_folders(tmp_path)
        assert result[0].name < result[1].name

    def test_empty_archive(self, tmp_path):
        result = find_uuid_folders(tmp_path)
        assert result == []

    def test_ignores_project_folders(self, tmp_path):
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()
        (tmp_path / "_legacy_something").mkdir()
        (tmp_path / ".hidden").mkdir()
        result = find_uuid_folders(tmp_path)
        assert result == []


# --- Phase 2: cwd extraction + project name derivation ---


class TestExtractCwdFromJsonl:
    def test_normal_cwd(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","sessionId":"abc","message":{}}\n'
        )
        assert (
            extract_cwd_from_jsonl(jsonl)
            == "/Users/testuser/CODE/CaptainCodeAU/My_Project"
        )

    def test_cwd_not_on_first_line(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            '{"type":"summary","summary":"warmup"}\n'
            '{"type":"ai-title","title":"test"}\n'
            '{"type":"user","cwd":"/Users/testuser/CODE/myproject","message":{}}\n'
        )
        assert extract_cwd_from_jsonl(jsonl) == "/Users/testuser/CODE/myproject"

    def test_no_cwd_field(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            '{"type":"queue-operation","action":"start"}\n'
            '{"type":"ai-title","title":"test"}\n'
        )
        assert extract_cwd_from_jsonl(jsonl) is None

    def test_blank_lines(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            "\n"
            "  \n"
            '{"type":"user","cwd":"/Users/testuser/CODE/myproject","message":{}}\n'
        )
        assert extract_cwd_from_jsonl(jsonl) == "/Users/testuser/CODE/myproject"

    def test_corrupt_json(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            "not valid json\n"
            "{also broken\n"
            '{"type":"user","cwd":"/Users/testuser/CODE/ok","message":{}}\n'
        )
        assert extract_cwd_from_jsonl(jsonl) == "/Users/testuser/CODE/ok"

    def test_all_corrupt(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text("not valid\nstill broken\n")
        assert extract_cwd_from_jsonl(jsonl) is None

    def test_empty_file(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text("")
        assert extract_cwd_from_jsonl(jsonl) is None

    def test_file_not_found(self, tmp_path):
        assert extract_cwd_from_jsonl(tmp_path / "nonexistent.jsonl") is None

    def test_empty_cwd_string_skipped(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            '{"type":"user","cwd":"","message":{}}\n'
            '{"type":"user","cwd":"/Users/testuser/CODE/real","message":{}}\n'
        )
        assert extract_cwd_from_jsonl(jsonl) == "/Users/testuser/CODE/real"


class TestExtractLastTimestamp:
    def test_extracts_last_timestamp(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text(
            '{"type":"user","timestamp":"2026-04-02T05:36:11.200Z","message":{}}\n'
            '{"type":"assistant","timestamp":"2026-04-02T06:00:00.000Z","message":{}}\n'
        )
        ts = extract_last_timestamp(jsonl)
        from datetime import datetime, timezone

        expected = datetime(2026, 4, 2, 6, 0, 0, tzinfo=timezone.utc).timestamp()
        assert abs(ts - expected) < 1

    def test_no_timestamp_returns_zero(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text('{"role":"user","message":{}}\n')
        assert extract_last_timestamp(jsonl) == 0.0

    def test_missing_file_returns_zero(self, tmp_path):
        assert extract_last_timestamp(tmp_path / "missing.jsonl") == 0.0


class TestCwdToProjectName:
    def test_standard_path(self):
        assert (
            cwd_to_project_name("/Users/testuser/CODE/CaptainCodeAU/My_Project")
            == "CaptainCodeAU-My-Project"
        )

    def test_simple_project(self):
        result = cwd_to_project_name("/Users/testuser/CODE/myproject")
        assert result == "myproject"

    def test_dotted_path(self):
        result = cwd_to_project_name("/Users/testuser/CODE/my.project")
        assert "my" in result and "project" in result


# --- Phase 3: Categorization ---


class TestCategorizeFolder:
    def test_with_jsonl(self, tmp_path):
        folder = tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92"
        folder.mkdir()
        jsonl = folder / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92.jsonl"
        jsonl.write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/proj","message":{}}\n'
        )
        (folder / "index.html").write_text("<html></html>")

        result = categorize_folder(folder)
        assert result.category == Category.A_JSONL
        assert result.jsonl_path == jsonl

    def test_html_only(self, tmp_path):
        folder = tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92"
        folder.mkdir()
        (folder / "index.html").write_text("<html></html>")
        (folder / "page-001.html").write_text("<html></html>")

        result = categorize_folder(folder)
        assert result.category == Category.B_HTML_ONLY
        assert len(result.html_files) == 2

    def test_empty(self, tmp_path):
        folder = tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92"
        folder.mkdir()

        result = categorize_folder(folder)
        assert result.category == Category.C_EMPTY

    def test_prefers_uuid_named_jsonl(self, tmp_path):
        folder = tmp_path / "aaaaaaaa-0000-0000-0000-000000000001"
        folder.mkdir()
        (folder / "other.jsonl").write_text('{"type":"user","cwd":"/other"}\n')
        (folder / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/correct","message":{}}\n'
        )
        result = categorize_folder(folder)
        assert result.cwd == "/correct"
        assert result.jsonl_path.name == "aaaaaaaa-0000-0000-0000-000000000001.jsonl"

    def test_other_files(self, tmp_path):
        folder = tmp_path / "f1a2a7f0-5057-43c9-8e59-163d2c2ceb92"
        folder.mkdir()
        (folder / "random.txt").write_text("hello")

        result = categorize_folder(folder)
        assert result.category == Category.D_OTHER


class TestCategorizeAll:
    def test_groups_correctly(self, tmp_path):
        # Category A
        a = tmp_path / "aaaaaaaa-0000-0000-0000-000000000001"
        a.mkdir()
        (a / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/test","message":{}}\n'
        )

        # Category B
        b = tmp_path / "bbbbbbbb-0000-0000-0000-000000000002"
        b.mkdir()
        (b / "index.html").write_text("<html></html>")

        # Category C
        c = tmp_path / "cccccccc-0000-0000-0000-000000000003"
        c.mkdir()

        folders = [a, b, c]
        result = categorize_all(folders)
        assert len(result[Category.A_JSONL]) == 1
        assert len(result[Category.B_HTML_ONLY]) == 1
        assert len(result[Category.C_EMPTY]) == 1
        assert len(result[Category.D_OTHER]) == 0


# --- Phase 4: Project matching ---


class TestFindMatchingProject:
    def test_exact_match(self):
        projects = ["CaptainCodeAU-My-Project", "CaptainCodeAU-other-project"]
        assert (
            find_matching_project("CaptainCodeAU-My-Project", projects)
            == "CaptainCodeAU-My-Project"
        )

    def test_case_insensitive(self):
        projects = ["CaptainCodeAU-My-Project"]
        assert (
            find_matching_project("captaincodeau-my-project", projects)
            == "CaptainCodeAU-My-Project"
        )

    def test_no_match(self):
        projects = ["CaptainCodeAU-My-Project"]
        assert find_matching_project("totally-different", projects) is None


class TestResolveTargetProject:
    def test_existing_project(self):
        existing = ["CaptainCodeAU-My-Project", "CaptainCodeAU-other-project"]
        name, is_new = resolve_target_project(
            "/Users/testuser/CODE/CaptainCodeAU/My_Project", existing
        )
        assert name == "CaptainCodeAU-My-Project"
        assert is_new is False

    def test_new_project(self):
        existing = ["CaptainCodeAU-other-project"]
        name, is_new = resolve_target_project(
            "/Users/testuser/CODE/CaptainCodeAU/brand_new_thing", existing
        )
        assert is_new is True
        assert "brand" in name and "new" in name and "thing" in name


# --- Phase 4b: HTML clue extraction ---


class TestExtractProjectFromHtml:
    def test_with_file_paths(self, tmp_path):
        html = tmp_path / "index.html"
        html.write_text(
            '<div class="tool-use">Read /Users/testuser/CODE/CaptainCodeAU/My_Project/main.py</div>'
        )
        result = extract_project_from_html(html)
        assert result is not None
        assert "Tax" in result

    def test_no_clues(self, tmp_path):
        html = tmp_path / "index.html"
        html.write_text("<html><body>Hello world</body></html>")
        assert extract_project_from_html(html) is None

    def test_preserves_dotted_directory_names(self, tmp_path):
        html = tmp_path / "index.html"
        html.write_text("<div>Read /Users/testuser/CODE/my.project/src/main.py</div>")
        result = extract_project_from_html(html)
        assert result is not None
        assert "my" in result

    def test_strips_file_extension(self, tmp_path):
        html = tmp_path / "index.html"
        html.write_text(
            "<div>Read /Users/testuser/CODE/CaptainCodeAU/proj/file.py</div>"
        )
        result = extract_project_from_html(html)
        assert result is not None
        assert "file" not in result.lower()

    def test_file_not_found(self, tmp_path):
        assert extract_project_from_html(tmp_path / "missing.html") is None


# --- Phase 4c: Human-readable sizes ---


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(0) == "0 B"
        assert _human_size(100) == "100 B"
        assert _human_size(999) == "999 B"

    def test_kilobytes(self):
        assert _human_size(1024) == "1.0 KB"
        assert _human_size(1536) == "1.5 KB"
        assert _human_size(10240) == "10.0 KB"

    def test_megabytes(self):
        assert _human_size(1048576) == "1.0 MB"
        assert _human_size(1039430) == "1015.1 KB"
        assert _human_size(3295100) == "3.1 MB"

    def test_gigabytes(self):
        assert _human_size(1073741824) == "1.0 GB"


class TestRelativeAge:
    def test_just_now(self):
        assert _relative_age(time.time()) == "just now"

    def test_minutes(self):
        assert _relative_age(time.time() - 120) == "2 m ago"

    def test_hours(self):
        assert _relative_age(time.time() - 7200) == "2 h ago"
        assert _relative_age(time.time() - 5400) == "1 h, 30 m ago"

    def test_days(self):
        assert _relative_age(time.time() - 259200) == "3 d ago"
        assert _relative_age(time.time() - 91800) == "1 d, 1 h, 30 m ago"

    def test_weeks(self):
        assert _relative_age(time.time() - 1209600) == "2 w ago"
        assert _relative_age(time.time() - 820800) == "1 w, 2 d, 12 h ago"

    def test_months(self):
        assert _relative_age(time.time() - 2592000) == "1 M ago"
        assert _relative_age(time.time() - 2894400) == "1 M, 3 d, 12 h ago"

    def test_four_levels_max(self):
        assert _relative_age(time.time() - 2895000) == "1 M, 3 d, 12 h, 10 m ago"
        # Verify it caps at 4 parts
        parts = _relative_age(time.time() - 34128060).replace(" ago", "").split(", ")
        assert len(parts) <= 4


# --- Phase 5: Duplicate comparison + Processing ---


class TestCompareSessionCopies:
    def test_identical_jsonl(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "session.jsonl").write_text("x" * 100)
        b = tmp_path / "organized"
        b.mkdir()
        (b / "session.jsonl").write_text("y" * 100)
        winner, reason = compare_session_copies(a, b)
        assert winner == "identical"

    def test_orphan_larger_jsonl(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "session.jsonl").write_text("x" * 200)
        b = tmp_path / "organized"
        b.mkdir()
        (b / "session.jsonl").write_text("y" * 100)
        winner, reason = compare_session_copies(a, b)
        assert winner == "orphan"
        assert "200 B" in reason

    def test_organized_larger_jsonl(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "session.jsonl").write_text("x" * 100)
        b = tmp_path / "organized"
        b.mkdir()
        (b / "session.jsonl").write_text("y" * 300)
        winner, reason = compare_session_copies(a, b)
        assert winner == "organized"
        assert "300 B" in reason

    def test_only_orphan_has_jsonl(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "session.jsonl").write_text("data")
        b = tmp_path / "organized"
        b.mkdir()
        (b / "index.html").write_text("<html></html>")
        winner, reason = compare_session_copies(a, b)
        assert winner == "orphan"

    def test_only_organized_has_jsonl(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "index.html").write_text("<html></html>")
        b = tmp_path / "organized"
        b.mkdir()
        (b / "session.jsonl").write_text("data")
        winner, reason = compare_session_copies(a, b)
        assert winner == "organized"

    def test_no_jsonl_in_either_similar_mtime(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "index.html").write_text("<html>a</html>")
        b = tmp_path / "organized"
        b.mkdir()
        (b / "index.html").write_text("<html>b</html>")
        winner, reason = compare_session_copies(a, b)
        assert winner == "identical"

    def test_prefers_uuid_named_jsonl(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        a = tmp_path / uuid
        a.mkdir()
        (a / f"{uuid}.jsonl").write_text("x" * 200)
        (a / "other.jsonl").write_text("y" * 50)
        b = tmp_path / "organized"
        b.mkdir()
        (b / f"{uuid}.jsonl").write_text("z" * 100)
        winner, reason = compare_session_copies(a, b)
        assert winner == "orphan"


def _make_uuid_folder(
    tmp_path, uuid, cwd="/Users/testuser/CODE/CaptainCodeAU/My_Project"
):
    folder = tmp_path / uuid
    folder.mkdir()
    jsonl = folder / f"{uuid}.jsonl"
    jsonl.write_text(f'{{"type":"user","cwd":"{cwd}","message":{{}}}}\n')
    return folder


class TestProcessCategoryA:
    def test_dry_run_no_move(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        cat = categorize_folder(folder)
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_a(cat, tmp_path, existing, dry_run=True)
        assert result.success is True
        assert folder.exists()
        assert result.target_project == "CaptainCodeAU-My-Project"

    @patch("reconcile_sessions.subprocess")
    def test_moves_folder(self, mock_subprocess, tmp_path):
        mock_subprocess.run.return_value = type(
            "R", (), {"returncode": 0, "stderr": ""}
        )()
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        cat = categorize_folder(folder)
        existing = ["CaptainCodeAU-My-Project"]
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        result = process_category_a(cat, tmp_path, existing, dry_run=False)
        assert result.success is True
        assert not folder.exists()
        assert (tmp_path / "CaptainCodeAU-My-Project" / uuid).exists()

    @patch("reconcile_sessions.subprocess")
    def test_creates_new_project(self, mock_subprocess, tmp_path):
        mock_subprocess.run.return_value = type(
            "R", (), {"returncode": 0, "stderr": ""}
        )()
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(
            tmp_path, uuid, cwd="/Users/testuser/CODE/CaptainCodeAU/brand_new"
        )
        cat = categorize_folder(folder)
        existing = []

        result = process_category_a(cat, tmp_path, existing, dry_run=False)
        assert result.success is True
        assert result.is_new_project is True

    def test_duplicate_identical_sizes(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        cat = categorize_folder(folder)
        proj_dir = tmp_path / "CaptainCodeAU-My-Project"
        proj_dir.mkdir()
        organized = proj_dir / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text((folder / f"{uuid}.jsonl").read_text())
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_a(cat, tmp_path, existing, dry_run=False)
        assert result.success is True
        assert result.is_duplicate is True

    @patch("reconcile_sessions.subprocess")
    def test_orphan_replaces_organized_when_larger(self, mock_subprocess, tmp_path):
        mock_subprocess.run.return_value = type(
            "R", (), {"returncode": 0, "stderr": ""}
        )()
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        orphan_content = (
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
            * 10
        )
        (folder / f"{uuid}.jsonl").write_text(orphan_content)
        cat = categorize_folder(folder)
        proj_dir = tmp_path / "CaptainCodeAU-My-Project"
        proj_dir.mkdir()
        organized = proj_dir / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
        )
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_a(cat, tmp_path, existing, dry_run=False)
        assert result.success is True
        assert result.replaced_organized is True
        assert not folder.exists()
        assert (proj_dir / uuid).exists()

    def test_orphan_replaces_organized_dry_run(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        orphan_content = (
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
            * 10
        )
        (folder / f"{uuid}.jsonl").write_text(orphan_content)
        cat = categorize_folder(folder)
        proj_dir = tmp_path / "CaptainCodeAU-My-Project"
        proj_dir.mkdir()
        organized = proj_dir / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
        )
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_a(cat, tmp_path, existing, dry_run=True)
        assert result.replaced_organized is True
        assert folder.exists()
        assert organized.exists()

    @patch("reconcile_sessions.subprocess")
    def test_regen_failure_flagged(self, mock_subprocess, tmp_path):
        mock_subprocess.run.return_value = type(
            "R", (), {"returncode": 1, "stderr": "error details"}
        )()
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        cat = categorize_folder(folder)
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_a(cat, tmp_path, existing, dry_run=False)
        assert result.success is True
        assert result.regen_failed is True
        assert result.regenerated is False

    def test_no_cwd_moves_to_unknown(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = tmp_path / uuid
        folder.mkdir()
        jsonl = folder / f"{uuid}.jsonl"
        jsonl.write_text('{"type":"queue-operation","action":"start"}\n')
        cat = categorize_folder(folder)
        existing = []

        result = process_category_a(cat, tmp_path, existing, dry_run=True)
        assert result.success is True
        assert result.is_unknown is True
        assert result.target_project == UNKNOWN_PROJECT


class TestProcessCategoryB:
    def test_moves_without_regen(self, tmp_path):
        uuid = "bbbbbbbb-0000-0000-0000-000000000002"
        folder = tmp_path / uuid
        folder.mkdir()
        html = folder / "index.html"
        html.write_text(
            "<div>Read /Users/testuser/CODE/CaptainCodeAU/My_Project/file.py</div>"
        )
        cat = categorize_folder(folder)
        proj_dir = tmp_path / "CaptainCodeAU-My-Project"
        proj_dir.mkdir()
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_b(cat, tmp_path, existing, dry_run=False)
        assert result.success is True
        assert not folder.exists()
        assert (proj_dir / uuid).exists()

    def test_dry_run_no_move(self, tmp_path):
        uuid = "bbbbbbbb-0000-0000-0000-000000000002"
        folder = tmp_path / uuid
        folder.mkdir()
        (folder / "index.html").write_text(
            "<div>Read /Users/testuser/CODE/CaptainCodeAU/My_Project/file.py</div>"
        )
        cat = categorize_folder(folder)
        existing = ["CaptainCodeAU-My-Project"]

        result = process_category_b(cat, tmp_path, existing, dry_run=True)
        assert result.success is True
        assert folder.exists()

    def test_no_clues_moves_to_unknown(self, tmp_path):
        uuid = "bbbbbbbb-0000-0000-0000-000000000002"
        folder = tmp_path / uuid
        folder.mkdir()
        (folder / "index.html").write_text("<html><body>No paths here</body></html>")
        cat = categorize_folder(folder)
        existing = []

        result = process_category_b(cat, tmp_path, existing, dry_run=True)
        assert result.success is True
        assert result.is_unknown is True
        assert result.target_project == UNKNOWN_PROJECT


# --- Phase 6: Reindex scanning ---


class TestListExistingProjects:
    def test_finds_project_dirs(self, tmp_path):
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()
        (tmp_path / "CaptainCodeAU-other-project").mkdir()
        (tmp_path / "aaaaaaaa-0000-0000-0000-000000000001").mkdir()
        (tmp_path / ".hidden").mkdir()

        result = list_existing_projects(tmp_path)
        assert "CaptainCodeAU-My-Project" in result
        assert "CaptainCodeAU-other-project" in result
        assert "aaaaaaaa-0000-0000-0000-000000000001" not in result
        assert ".hidden" not in result

    def test_excludes_legacy_dirs(self, tmp_path):
        (tmp_path / "_legacy_My_Project").mkdir()
        (tmp_path / "_my_backup").mkdir()
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        result = list_existing_projects(tmp_path)
        assert "_legacy_My_Project" not in result
        assert "_my_backup" not in result
        assert "CaptainCodeAU-My-Project" in result


class TestScanArchiveForProjects:
    def test_scans_project_sessions(self, tmp_path):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        jsonl = session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl"
        jsonl.write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )

        result = scan_archive_for_projects(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "MyProject"
        assert len(result[0]["sessions"]) == 1
        assert (
            result[0]["sessions"][0]["path"].stem
            == "aaaaaaaa-0000-0000-0000-000000000001"
        )

    def test_skips_uuid_dirs_at_root(self, tmp_path):
        (tmp_path / "aaaaaaaa-0000-0000-0000-000000000001").mkdir()
        result = scan_archive_for_projects(tmp_path)
        assert len(result) == 0

    def test_skips_hidden_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = scan_archive_for_projects(tmp_path)
        assert len(result) == 0

    def test_empty_project(self, tmp_path):
        (tmp_path / "EmptyProject").mkdir()
        result = scan_archive_for_projects(tmp_path)
        assert len(result) == 1
        assert result[0]["sessions"] == []

    def test_html_only_session(self, tmp_path):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        session = proj / "bbbbbbbb-0000-0000-0000-000000000002"
        session.mkdir()
        (session / "index.html").write_text(
            "<html><head><title>Test Session</title></head><body>content</body></html>"
        )

        result = scan_archive_for_projects(tmp_path)
        assert len(result[0]["sessions"]) == 1
        assert (
            result[0]["sessions"][0]["path"].stem
            == "bbbbbbbb-0000-0000-0000-000000000002"
        )

    def test_skips_non_session_subdirs(self, tmp_path):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        backup = proj / "_backup"
        backup.mkdir()
        (backup / "notes.txt").write_text("hi")
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        (session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )

        result = scan_archive_for_projects(tmp_path)
        assert len(result[0]["sessions"]) == 1

    def test_empty_session_folder_skipped(self, tmp_path):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        (proj / "cccccccc-0000-0000-0000-000000000003").mkdir()

        result = scan_archive_for_projects(tmp_path)
        assert len(result[0]["sessions"]) == 0


# --- Phase 6b: Move plan ---


class TestComputeMovePlan:
    def test_jsonl_to_existing_project(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        cat = categorize_folder(folder)
        categories = {c: [] for c in Category}
        categories[Category.A_JSONL] = [cat]
        existing = ["CaptainCodeAU-My-Project"]

        plan = compute_move_plan(categories, tmp_path, existing)
        assert len(plan) == 1
        assert plan[0].target_project == "CaptainCodeAU-My-Project"
        assert plan[0].duplicate_status == ""
        assert plan[0].is_new_project is False

    def test_new_project_detected(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        _make_uuid_folder(
            tmp_path, uuid, cwd="/Users/testuser/CODE/CaptainCodeAU/brand_new"
        )
        cat = categorize_folder(tmp_path / uuid)
        categories = {c: [] for c in Category}
        categories[Category.A_JSONL] = [cat]

        plan = compute_move_plan(categories, tmp_path, [])
        assert plan[0].is_new_project is True

    def test_duplicate_skip(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text((folder / f"{uuid}.jsonl").read_text())
        cat = categorize_folder(folder)
        categories = {c: [] for c in Category}
        categories[Category.A_JSONL] = [cat]

        plan = compute_move_plan(categories, tmp_path, ["CaptainCodeAU-My-Project"])
        assert plan[0].duplicate_status == "skip"

    def test_duplicate_replace(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        (folder / f"{uuid}.jsonl").write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
            * 10
        )
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
        )
        cat = categorize_folder(folder)
        categories = {c: [] for c in Category}
        categories[Category.A_JSONL] = [cat]

        plan = compute_move_plan(categories, tmp_path, ["CaptainCodeAU-My-Project"])
        assert plan[0].duplicate_status == "replace"
        assert plan[0].duplicate_reason != ""

    def test_html_folder_resolved(self, tmp_path):
        uuid = "bbbbbbbb-0000-0000-0000-000000000002"
        folder = tmp_path / uuid
        folder.mkdir()
        (folder / "index.html").write_text(
            "<div>Read /Users/testuser/CODE/CaptainCodeAU/My_Project/file.py</div>"
        )
        cat = categorize_folder(folder)
        categories = {c: [] for c in Category}
        categories[Category.B_HTML_ONLY] = [cat]

        plan = compute_move_plan(categories, tmp_path, ["CaptainCodeAU-My-Project"])
        assert len(plan) == 1
        assert plan[0].target_project == "CaptainCodeAU-My-Project"
        assert plan[0].category_label == "HTML"

    def test_unknown_cwd(self, tmp_path):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = tmp_path / uuid
        folder.mkdir()
        (folder / f"{uuid}.jsonl").write_text(
            '{"type":"queue-operation","action":"start"}\n'
        )
        cat = categorize_folder(folder)
        categories = {c: [] for c in Category}
        categories[Category.A_JSONL] = [cat]

        plan = compute_move_plan(categories, tmp_path, [])
        assert plan[0].is_unknown is True
        assert plan[0].target_project == UNKNOWN_PROJECT

    def test_two_folders_same_new_project_only_first_is_new(self, tmp_path):
        for i in range(2):
            uuid = f"aaaaaaaa-0000-0000-0000-00000000000{i+1}"
            _make_uuid_folder(
                tmp_path, uuid, cwd="/Users/testuser/CODE/CaptainCodeAU/brand_new"
            )
        cats = {c: [] for c in Category}
        for i in range(2):
            uuid = f"aaaaaaaa-0000-0000-0000-00000000000{i+1}"
            cats[Category.A_JSONL].append(categorize_folder(tmp_path / uuid))

        plan = compute_move_plan(cats, tmp_path, [])
        new_flags = [p.is_new_project for p in plan]
        assert new_flags[0] is True
        assert new_flags[1] is False


class TestFormatMovePlan:
    def test_includes_uuid_and_project(self):
        plan = [
            PlannedMove(
                uuid="aaaaaaaa-0000-0000-0000-000000000001",
                source=Path("/tmp/aaa"),
                target_project="MyProject",
                is_new_project=False,
                duplicate_status="",
                duplicate_reason="",
                is_unknown=False,
                category_label="JSONL",
            ),
        ]
        output = format_move_plan(plan)
        assert "aaaaaaaa-0000-0000-0000-000000000001" in output
        assert "MyProject" in output
        assert "Move" in output

    def test_shows_move_group_with_new_tag(self):
        plan = [
            PlannedMove(
                uuid="aaa",
                source=Path("/tmp/aaa"),
                target_project="NewProj",
                is_new_project=True,
                duplicate_status="",
                duplicate_reason="",
                is_unknown=False,
                category_label="JSONL",
            ),
        ]
        output = format_move_plan(plan)
        assert "Move" in output
        assert "new project" in output

    def test_shows_replace_group_with_delta(self, tmp_path):
        folder = tmp_path / "aaa"
        folder.mkdir()
        (folder / "aaa.jsonl").write_text("x" * 200)
        plan = [
            PlannedMove(
                uuid="aaa",
                source=folder,
                target_project="Proj",
                is_new_project=False,
                duplicate_status="replace",
                duplicate_reason="incoming 200 B vs existing 100 B",
                is_unknown=False,
                category_label="JSONL",
                size_delta=100,
            ),
        ]
        output = format_move_plan(plan)
        assert "Replace" in output
        assert "+100 B" in output

    def test_groups_skip_duplicates(self):
        plan = [
            PlannedMove(
                uuid="aaa",
                source=Path("/tmp/aaa"),
                target_project="Proj",
                is_new_project=False,
                duplicate_status="skip",
                duplicate_reason="identical",
                is_unknown=False,
                category_label="JSONL",
            ),
        ]
        output = format_move_plan(plan)
        assert "duplicate" in output.lower()
        assert "aaa" in output

    def test_empty_plan_returns_empty(self):
        assert format_move_plan([]) == ""

    def test_shows_unknown_group(self):
        plan = [
            PlannedMove(
                uuid="aaa",
                source=Path("/tmp/aaa"),
                target_project="_UNKNOWN",
                is_new_project=True,
                duplicate_status="",
                duplicate_reason="",
                is_unknown=True,
                category_label="JSONL",
            ),
        ]
        output = format_move_plan(plan)
        assert "UNKNOWN" in output

    def test_shows_inline_age(self):
        plan = [
            PlannedMove(
                uuid="aaa",
                source=Path("/tmp/aaa"),
                target_project="Proj",
                is_new_project=True,
                duplicate_status="",
                duplicate_reason="",
                is_unknown=False,
                category_label="JSONL",
                source_mtime=time.time() - 3600,
            ),
        ]
        output = format_move_plan(plan)
        assert "1 h ago" in output
        # Age should be on the same line as the UUID, not a separate line
        for line in output.split("\n"):
            if "aaa" in line and "Proj" in line:
                assert "1 h ago" in line
                break

    def test_shows_total_line(self, tmp_path):
        folder = tmp_path / "aaa"
        folder.mkdir()
        (folder / "aaa.jsonl").write_text("x" * 500)
        plan = [
            PlannedMove(
                uuid="aaa",
                source=folder,
                target_project="Proj",
                is_new_project=True,
                duplicate_status="",
                duplicate_reason="",
                is_unknown=False,
                category_label="JSONL",
            ),
        ]
        output = format_move_plan(plan)
        assert "Summary:" in output
        assert "Add new" in output
        assert "session" in output


# --- Phase 7: Report + main integration ---


class TestFormatCategoryTable:
    def test_includes_counts(self):
        categories = {
            Category.A_JSONL: [None, None, None],
            Category.B_HTML_ONLY: [None],
            Category.C_EMPTY: [None, None],
            Category.D_OTHER: [],
        }
        output = format_category_table(categories)
        assert "3" in output
        assert "1" in output
        assert "2" in output
        assert "0" in output


class TestFormatReport:
    def test_includes_summary(self):
        report = ReconciliationReport(
            moved_jsonl=5,
            moved_html=2,
            moved_unknown=1,
            replaced=3,
            already_organized=10,
            skipped_empty=1,
            failed=1,
            new_projects=["NewProj"],
            outliers=[("abc-uuid", "Some error")],
            projects_affected={"ProjA", "ProjB", "NewProj"},
            reindexed=False,
        )
        output = format_report(report)
        assert "NewProj" in output
        assert "abc-uuid" in output
        assert "Already organized" in output
        assert "unknown" in output.lower()
        assert "Replaced" in output

    def test_shows_elapsed_time(self):
        report = ReconciliationReport(elapsed_seconds=42.3)
        output = format_report(report)
        assert "42.3" in output


class TestMainDryRun:
    @patch("reconcile_sessions.subprocess")
    def test_dry_run_no_changes(self, mock_subprocess, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        main(["--dry-run", "--yes", str(tmp_path)])

        assert folder.exists()
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out or "dry" in captured.out.lower()

    def test_duplicates_reported_as_organized(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text((folder / f"{uuid}.jsonl").read_text())

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "duplicate" in captured.out.lower()

    def test_verbose_dry_run_shows_targets(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        _make_uuid_folder(tmp_path, uuid)
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        main(["--dry-run", "--yes", "--verbose", str(tmp_path)])

        captured = capsys.readouterr()
        assert "CaptainCodeAU-My-Project" in captured.out

    def test_non_tty_output_no_carriage_return(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        _make_uuid_folder(tmp_path, uuid)
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "\r" not in captured.out

    def test_category_d_lists_file_names(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = tmp_path / uuid
        folder.mkdir()
        (folder / "random.txt").write_text("hello")
        (folder / "data.csv").write_text("a,b")

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "random.txt" in captured.out
        assert "data.csv" in captured.out

    def test_new_projects_not_duplicated(self, tmp_path, capsys):
        for i in range(2):
            uuid = f"aaaaaaaa-0000-0000-0000-00000000000{i+1}"
            _make_uuid_folder(
                tmp_path, uuid, cwd="/Users/testuser/CODE/CaptainCodeAU/brand_new"
            )

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        lines = [
            l
            for l in captured.out.split("\n")
            if "brand" in l.lower() or "new" in l.lower()
        ]
        project_lines = [l for l in lines if l.strip().startswith("- ")]
        assert len(project_lines) <= 1

    def test_elapsed_time_shown(self, tmp_path, capsys):
        (tmp_path / "SomeProject").mkdir()
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        _make_uuid_folder(tmp_path, uuid)

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Elapsed" in captured.out

    def test_archive_summary_shown(self, tmp_path, capsys):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        (session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )
        _make_uuid_folder(tmp_path, "bbbbbbbb-0000-0000-0000-000000000002")

        main(["--dry-run", "--no-reindex", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Archive:" in captured.out
        assert "Projects:" in captured.out
        assert "Sessions:" in captured.out

    def test_clean_archive_shows_summary(self, tmp_path, capsys):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        (session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )

        with pytest.raises(SystemExit):
            main(["--no-reindex", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Archive:" in captured.out
        assert "clean" in captured.out.lower()

    def test_no_orphans_with_no_reindex_exits(self, tmp_path, capsys):
        (tmp_path / "SomeProject").mkdir()

        with pytest.raises(SystemExit) as exc_info:
            main(["--no-reindex", "--yes", str(tmp_path)])
        assert exc_info.value.code == 0

    def test_no_orphans_still_reindexes_by_default(self, tmp_path, capsys):
        proj = tmp_path / "SomeProject"
        proj.mkdir()
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        (session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )

        main(["--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Rebuilding indexes" in captured.out
        assert (tmp_path / "index.html").exists()

    @patch("reconcile_sessions.subprocess")
    def test_reindex_runs_by_default(self, mock_subprocess, tmp_path, capsys):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        jsonl = session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl"
        jsonl.write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )

        main(["--yes", str(tmp_path)])

        assert (proj / "index.html").exists()
        assert (tmp_path / "index.html").exists()

    def test_cleanup_moves_to_delete_folder(self, tmp_path, capsys):
        uuid_dup = "aaaaaaaa-0000-0000-0000-000000000001"
        orphan = _make_uuid_folder(tmp_path, uuid_dup)
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid_dup
        organized.mkdir()
        (organized / f"{uuid_dup}.jsonl").write_text(
            (orphan / f"{uuid_dup}.jsonl").read_text()
        )

        uuid_empty = "bbbbbbbb-0000-0000-0000-000000000002"
        empty_folder = tmp_path / uuid_empty
        empty_folder.mkdir()

        main(["--cleanup", "--no-reindex", "--yes", str(tmp_path)])

        assert not orphan.exists()
        assert not empty_folder.exists()
        assert organized.exists()
        delete_dir = tmp_path / "_DELETE"
        assert delete_dir.exists()
        assert (delete_dir / "duplicates" / uuid_dup).exists()
        assert (delete_dir / "empty" / uuid_empty).exists()

    def test_cleanup_dry_run_preserves_folders(self, tmp_path, capsys):
        uuid_dup = "aaaaaaaa-0000-0000-0000-000000000001"
        orphan = _make_uuid_folder(tmp_path, uuid_dup)
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid_dup
        organized.mkdir()
        (organized / f"{uuid_dup}.jsonl").write_text(
            (orphan / f"{uuid_dup}.jsonl").read_text()
        )

        main(["--cleanup", "--dry-run", "--no-reindex", "--yes", str(tmp_path)])

        assert orphan.exists()
        captured = capsys.readouterr()
        assert "would move" in captured.out.lower()

    def test_cleanup_report_shows_counts(self, tmp_path, capsys):
        uuid_dup = "aaaaaaaa-0000-0000-0000-000000000001"
        orphan = _make_uuid_folder(tmp_path, uuid_dup)
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid_dup
        organized.mkdir()
        (organized / f"{uuid_dup}.jsonl").write_text(
            (orphan / f"{uuid_dup}.jsonl").read_text()
        )

        main(["--cleanup", "--no-reindex", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Duplicates" in captured.out

    def test_move_plan_shown_before_processing(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        _make_uuid_folder(tmp_path, uuid)
        (tmp_path / "CaptainCodeAU-My-Project").mkdir()

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Move plan" in captured.out
        assert "CaptainCodeAU-My-Project" in captured.out

    def test_move_plan_shows_new_project_tag(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        _make_uuid_folder(
            tmp_path, uuid, cwd="/Users/testuser/CODE/CaptainCodeAU/brand_new"
        )

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "new project" in captured.out

    def test_move_plan_shows_duplicate_skip(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text((folder / f"{uuid}.jsonl").read_text())

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "duplicate" in captured.out.lower()
        assert uuid in captured.out

    def test_move_plan_shows_replace(self, tmp_path, capsys):
        uuid = "aaaaaaaa-0000-0000-0000-000000000001"
        folder = _make_uuid_folder(tmp_path, uuid)
        (folder / f"{uuid}.jsonl").write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
            * 10
        )
        proj = tmp_path / "CaptainCodeAU-My-Project"
        proj.mkdir()
        organized = proj / uuid
        organized.mkdir()
        (organized / f"{uuid}.jsonl").write_text(
            '{"type":"user","cwd":"/Users/testuser/CODE/CaptainCodeAU/My_Project","message":{}}\n'
        )

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "Replace" in captured.out

    @patch("reconcile_sessions.subprocess")
    def test_no_reindex_skips_index_rebuild(self, mock_subprocess, tmp_path, capsys):
        mock_subprocess.run.return_value = type(
            "R", (), {"returncode": 0, "stderr": ""}
        )()
        proj = tmp_path / "MyProject"
        proj.mkdir()
        _make_uuid_folder(
            tmp_path,
            "aaaaaaaa-0000-0000-0000-000000000001",
            cwd="/Users/testuser/CODE/MyProject",
        )

        main(["--no-reindex", "--yes", str(tmp_path)])

        assert not (proj / "index.html").exists()
        assert not (tmp_path / "index.html").exists()

    def test_dry_run_skips_reindex(self, tmp_path, capsys):
        proj = tmp_path / "MyProject"
        proj.mkdir()
        session = proj / "aaaaaaaa-0000-0000-0000-000000000001"
        session.mkdir()
        (session / "aaaaaaaa-0000-0000-0000-000000000001.jsonl").write_text(
            '{"type":"user","cwd":"/test","message":{"content":"hello"}}\n'
        )
        _make_uuid_folder(tmp_path, "bbbbbbbb-0000-0000-0000-000000000002")

        main(["--dry-run", "--yes", str(tmp_path)])

        captured = capsys.readouterr()
        assert "skipped (dry run)" in captured.out
        assert not (tmp_path / "index.html").exists()


class TestMoveToDeleteFolder:
    def test_moves_to_delete_dir(self, tmp_path):
        source = tmp_path / "aaaaaaaa-0000-0000-0000-000000000001"
        source.mkdir()
        (source / "test.txt").write_text("hello")

        result = move_to_delete_folder(source, tmp_path)

        assert not source.exists()
        assert result.parent.name == "duplicates"
        assert (tmp_path / "_DELETE" / "duplicates" / source.name / "test.txt").exists()

    def test_creates_delete_dir_with_subfolder(self, tmp_path):
        source = tmp_path / "aaaaaaaa-0000-0000-0000-000000000001"
        source.mkdir()

        move_to_delete_folder(source, tmp_path, subfolder="empty")

        assert (tmp_path / "_DELETE" / "empty").exists()

    def test_collision_appends_suffix(self, tmp_path):
        (tmp_path / "_DELETE" / "duplicates").mkdir(parents=True)
        existing = tmp_path / "_DELETE" / "duplicates" / "aaa"
        existing.mkdir()

        source = tmp_path / "aaa"
        source.mkdir()
        (source / "file.txt").write_text("new")

        result = move_to_delete_folder(source, tmp_path)

        assert result.name == "aaa-1"
        assert (tmp_path / "_DELETE" / "duplicates" / "aaa-1" / "file.txt").exists()

    def test_multiple_collisions(self, tmp_path):
        (tmp_path / "_DELETE" / "duplicates").mkdir(parents=True)
        (tmp_path / "_DELETE" / "duplicates" / "aaa").mkdir()
        (tmp_path / "_DELETE" / "duplicates" / "aaa-1").mkdir()

        source = tmp_path / "aaa"
        source.mkdir()

        result = move_to_delete_folder(source, tmp_path)

        assert result.name == "aaa-2"


class TestFormatDeletePlan:
    def test_shows_duplicates(self):
        paths = [Path("/archive/aaa"), Path("/archive/bbb")]
        output = format_delete_plan(paths, [])
        assert "DUPLICATES" in output
        assert "aaa" in output
        assert "bbb" in output

    def test_shows_empties(self):
        paths = [Path("/archive/ccc")]
        output = format_delete_plan([], paths)
        assert "EMPTY" in output
        assert "ccc" in output

    def test_empty_lists_returns_empty(self):
        assert format_delete_plan([], []) == ""

    def test_shows_both(self):
        output = format_delete_plan([Path("/archive/dup")], [Path("/archive/empty")])
        assert "DUPLICATES" in output
        assert "EMPTY" in output

    def test_shows_duplicate_reasons(self):
        paths = [Path("/archive/aaa")]
        reasons = {"aaa": "both 512 B"}
        output = format_delete_plan(paths, [], reasons)
        assert "both 512 B" in output


class TestScanArchiveSkipsUnderscore:
    def test_skips_delete_folder(self, tmp_path):
        (tmp_path / "_DELETE").mkdir()
        (tmp_path / "RealProject").mkdir()
        result = scan_archive_for_projects(tmp_path)
        names = [p["name"] for p in result]
        assert "_DELETE" not in names
        assert "RealProject" in names
