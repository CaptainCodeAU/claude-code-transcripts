"""Tests for scripts/reconcile_sessions.py"""

import sys
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
    ReconciliationReport,
    categorize_all,
    categorize_folder,
    compare_session_copies,
    cwd_to_project_name,
    extract_cwd_from_jsonl,
    extract_project_from_html,
    find_matching_project,
    find_uuid_folders,
    format_category_table,
    format_report,
    list_existing_projects,
    main,
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
        assert "200" in reason

    def test_organized_larger_jsonl(self, tmp_path):
        a = tmp_path / "orphan"
        a.mkdir()
        (a / "session.jsonl").write_text("x" * 100)
        b = tmp_path / "organized"
        b.mkdir()
        (b / "session.jsonl").write_text("y" * 300)
        winner, reason = compare_session_copies(a, b)
        assert winner == "organized"
        assert "300" in reason

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
        assert "Already organized" in captured.out

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

    def test_cleanup_deletes_duplicates_and_empties(self, tmp_path, capsys):
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
        captured = capsys.readouterr()
        assert "Cleaning up" in captured.out

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
        assert "would delete" in captured.out

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
        assert "Deleted duplicates" in captured.out

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
