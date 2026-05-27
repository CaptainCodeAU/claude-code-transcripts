"""Tests for scripts/migrate_project.py"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from migrate_project import (
    apply_memory_replacements,
    count_contents,
    display_tilde,
    encode_path,
    find_matching_directories,
    get_os_root,
    main,
    parse_remote_url,
    parse_ssh_aliases,
    prompt_3rdparty,
    scan_memory_files,
    tilde_form,
)

# --- Path encoding ---


class TestEncodePath:
    def test_slashes_become_dashes(self):
        assert encode_path("/Users/testuser/CODE") == "-Users-testuser-CODE"

    def test_underscores_become_dashes(self):
        assert encode_path("/home/user/My_Project") == "-home-user-My-Project"

    def test_dots_become_dashes(self):
        assert encode_path("/home/user/.worktree-web") == "-home-user--worktree-web"

    def test_full_mac_path(self):
        assert (
            encode_path("/Users/testuser/CODE/TestOwner/claude-code-transcripts")
            == "-Users-testuser-CODE-TestOwner-claude-code-transcripts"
        )

    def test_full_linux_path(self):
        assert (
            encode_path("/home/testuser/repos/test-project")
            == "-home-testuser-repos-test-project"
        )

    def test_combined_special_chars(self):
        assert (
            encode_path("/home/user/my_project.v2/src")
            == "-home-user-my-project-v2-src"
        )


# --- Tilde form ---


class TestTildeForm:
    def test_converts_home_to_tilde(self):
        home = str(Path.home())
        assert tilde_form(f"{home}/CODE/myproject") == "~/CODE/myproject"

    def test_non_home_path_unchanged(self):
        assert tilde_form("/tmp/something") == "/tmp/something"

    def test_exact_home_path(self):
        home = str(Path.home())
        assert tilde_form(home) == "~"


class TestDisplayTilde:
    def test_converts_path_to_tilde(self):
        result = display_tilde(Path.home() / "CODE" / "myproject")
        assert result == "~/CODE/myproject"

    def test_non_home_path_unchanged(self):
        assert display_tilde(Path("/tmp/something")) == "/tmp/something"


# --- Remote URL parsing ---


class TestParseRemoteUrl:
    def test_ssh_alias_with_dotgit(self):
        result = parse_remote_url("git-test:TestOwner/repo.git")
        assert result == ("git-test", "TestOwner", "repo")

    def test_ssh_alias_without_dotgit(self):
        result = parse_remote_url("git-test:TestOwner/repo")
        assert result == ("git-test", "TestOwner", "repo")

    def test_ssh_standard_with_user(self):
        result = parse_remote_url("git@github.com:TestOwner/repo.git")
        assert result == ("github.com", "TestOwner", "repo")

    def test_ssh_standard_without_dotgit(self):
        result = parse_remote_url("git@github.com:Owner/repo-name")
        assert result == ("github.com", "Owner", "repo-name")

    def test_https_with_dotgit(self):
        result = parse_remote_url("https://github.com/TestOwner/repo.git")
        assert result == ("github.com", "TestOwner", "repo")

    def test_https_without_dotgit(self):
        result = parse_remote_url("https://github.com/Owner/my-repo")
        assert result == ("github.com", "Owner", "my-repo")

    def test_http_url(self):
        result = parse_remote_url("http://github.com/Owner/repo.git")
        assert result == ("github.com", "Owner", "repo")

    def test_preserves_owner_case(self):
        result = parse_remote_url("git-test:TestOwner/Repo-Name.git")
        assert result[1] == "TestOwner"

    def test_strips_whitespace(self):
        result = parse_remote_url("  git-test:Owner/repo.git  \n")
        assert result == ("git-test", "Owner", "repo")

    def test_empty_string_returns_none(self):
        assert parse_remote_url("") is None

    def test_garbage_returns_none(self):
        assert parse_remote_url("not-a-url") is None

    def test_missing_repo_returns_none(self):
        assert parse_remote_url("git-test:owner-only") is None

    def test_hyphenated_alias(self):
        result = parse_remote_url("git-other:OtherOwner/Classes.git")
        assert result == ("git-other", "OtherOwner", "Classes")

    def test_repo_with_dots(self):
        result = parse_remote_url("git-test:Owner/my.repo.v2.git")
        assert result == ("git-test", "Owner", "my.repo.v2")

    def test_3rdparty_ssh(self):
        result = parse_remote_url("git@github.com:microsoft/markitdown.git")
        assert result == ("github.com", "microsoft", "markitdown")


# --- SSH config parsing ---


class TestParseSSHAliases:
    def test_parses_git_aliases(self, tmp_path):
        config = tmp_path / "config.local"
        config.write_text(
            "Host git-test\n"
            "    HostName github.com\n"
            "    User git\n"
            "\n"
            "Host git-other2\n"
            "    HostName github.com\n"
        )
        result = parse_ssh_aliases(config)
        assert result == {"git-test", "git-other2"}

    def test_ignores_non_git_hosts(self, tmp_path):
        config = tmp_path / "config.local"
        config.write_text(
            "Host server.lan\n"
            "    HostName 10.0.0.1\n"
            "\n"
            "Host git-test\n"
            "    HostName github.com\n"
        )
        result = parse_ssh_aliases(config)
        assert result == {"git-test"}

    def test_ignores_host_wildcard(self, tmp_path):
        config = tmp_path / "config.local"
        config.write_text("Host *\n    AddKeysToAgent no\n")
        result = parse_ssh_aliases(config)
        assert result == set()

    def test_multiple_names_on_one_line(self, tmp_path):
        config = tmp_path / "config.local"
        config.write_text("Host github.com git-test\n    HostName github.com\n")
        result = parse_ssh_aliases(config)
        assert result == {"git-test"}

    def test_missing_file_returns_empty(self, tmp_path):
        result = parse_ssh_aliases(tmp_path / "nonexistent")
        assert result == set()

    def test_empty_file_returns_empty(self, tmp_path):
        config = tmp_path / "config.local"
        config.write_text("")
        result = parse_ssh_aliases(config)
        assert result == set()

    def test_case_insensitive_host_keyword(self, tmp_path):
        config = tmp_path / "config.local"
        config.write_text("host git-test\n    HostName github.com\n")
        result = parse_ssh_aliases(config)
        assert result == {"git-test"}


# --- OS root detection ---


class TestGetOsRoot:
    @patch("migrate_project.platform.system", return_value="Darwin")
    def test_macos_returns_code(self, _mock):
        assert get_os_root() == Path.home() / "CODE"

    @patch("migrate_project.platform.system", return_value="Linux")
    def test_linux_returns_repos(self, _mock):
        assert get_os_root() == Path.home() / "repos"

    @patch("migrate_project.platform.system", return_value="Windows")
    def test_windows_returns_repos(self, _mock):
        assert get_os_root() == Path.home() / "repos"


# --- Claude project directory scanning ---


class TestFindMatchingDirectories:
    def test_finds_exact_match(self, tmp_path):
        d = tmp_path / "-home-user-repos-myproject"
        d.mkdir()
        result = find_matching_directories(tmp_path, "-home-user-repos-myproject")
        assert result == [d]

    def test_finds_subproject_dirs(self, tmp_path):
        main = tmp_path / "-home-user-repos-myproject"
        main.mkdir()
        cli = tmp_path / "-home-user-repos-myproject-cli"
        cli.mkdir()
        svc = tmp_path / "-home-user-repos-myproject-services-web"
        svc.mkdir()
        result = find_matching_directories(tmp_path, "-home-user-repos-myproject")
        assert result == [main, cli, svc]

    def test_excludes_partial_name_match(self, tmp_path):
        (tmp_path / "-home-user-repos-myproject").mkdir()
        (tmp_path / "-home-user-repos-myprojectx").mkdir()
        result = find_matching_directories(tmp_path, "-home-user-repos-myproject")
        assert len(result) == 1
        assert result[0].name == "-home-user-repos-myproject"

    def test_returns_empty_for_no_matches(self, tmp_path):
        (tmp_path / "unrelated-dir").mkdir()
        result = find_matching_directories(tmp_path, "-home-user-repos-myproject")
        assert result == []

    def test_returns_empty_for_nonexistent_dir(self, tmp_path):
        result = find_matching_directories(tmp_path / "nope", "-prefix")
        assert result == []

    def test_ignores_files(self, tmp_path):
        (tmp_path / "-home-user-repos-myproject").write_text("not a dir")
        result = find_matching_directories(tmp_path, "-home-user-repos-myproject")
        assert result == []

    def test_sorted_output(self, tmp_path):
        (tmp_path / "-prefix-zzz").mkdir()
        (tmp_path / "-prefix-aaa").mkdir()
        (tmp_path / "-prefix").mkdir()
        result = find_matching_directories(tmp_path, "-prefix")
        names = [r.name for r in result]
        assert names == ["-prefix", "-prefix-aaa", "-prefix-zzz"]


class TestCountContents:
    def test_counts_memory_and_sessions(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "file1.md").write_text("x")
        (mem / "file2.md").write_text("x")
        (tmp_path / "session1.jsonl").write_text("x")
        (tmp_path / "session2.jsonl").write_text("x")
        (tmp_path / "session3.jsonl").write_text("x")
        assert count_contents(tmp_path) == (2, 3)

    def test_no_memory_dir(self, tmp_path):
        (tmp_path / "session.jsonl").write_text("x")
        assert count_contents(tmp_path) == (0, 1)

    def test_empty_directory(self, tmp_path):
        assert count_contents(tmp_path) == (0, 0)

    def test_ignores_non_jsonl_files(self, tmp_path):
        (tmp_path / "settings.json").write_text("x")
        (tmp_path / "notes.txt").write_text("x")
        assert count_contents(tmp_path) == (0, 0)

    def test_nested_memory_files(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        subdir = mem / "subdir"
        subdir.mkdir()
        (subdir / "deep.md").write_text("x")
        (mem / "top.md").write_text("x")
        assert count_contents(tmp_path) == (2, 0)


# --- Memory file scanning and replacement ---


class TestScanMemoryFiles:
    def test_finds_matching_references(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "note.md").write_text("path: /old/path/project\nother line\n")
        patterns = [("/old/path/project", "/new/path/project")]
        result = scan_memory_files(tmp_path, patterns)
        assert len(result) == 1
        assert result[0][1] == 1

    def test_counts_multiple_refs_in_one_file(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "note.md").write_text("/old/path\nsomething\n/old/path again\n")
        patterns = [("/old/path", "/new/path")]
        result = scan_memory_files(tmp_path, patterns)
        assert result[0][1] == 2

    def test_counts_across_pattern_types(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "note.md").write_text("/abs/old/path\n~/old/path\n-abs-old-path\n")
        patterns = [
            ("/abs/old/path", "/abs/new/path"),
            ("~/old/path", "~/new/path"),
            ("-abs-old-path", "-abs-new-path"),
        ]
        result = scan_memory_files(tmp_path, patterns)
        assert result[0][1] == 3

    def test_skips_files_without_matches(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "clean.md").write_text("nothing relevant here\n")
        patterns = [("/old/path", "/new/path")]
        result = scan_memory_files(tmp_path, patterns)
        assert result == []

    def test_no_memory_dir(self, tmp_path):
        patterns = [("/old", "/new")]
        assert scan_memory_files(tmp_path, patterns) == []

    def test_skips_binary_files(self, tmp_path):
        mem = tmp_path / "memory"
        mem.mkdir()
        (mem / "binary.bin").write_bytes(b"\x00\x01\x02\xff")
        patterns = [("/old", "/new")]
        result = scan_memory_files(tmp_path, patterns)
        assert result == []


class TestApplyMemoryReplacements:
    def test_replaces_all_forms(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text(
            "abs: /old/path/project\n"
            "tilde: ~/old/path/project\n"
            "encoded: -old-path-project\n"
        )
        patterns = [
            ("/old/path/project", "/new/path/project"),
            ("~/old/path/project", "~/new/path/project"),
            ("-old-path-project", "-new-path-project"),
        ]
        changed = apply_memory_replacements(f, patterns)
        assert changed == 3
        content = f.read_text()
        assert "/new/path/project" in content
        assert "~/new/path/project" in content
        assert "-new-path-project" in content
        assert "/old/path/project" not in content

    def test_no_matches_returns_zero(self, tmp_path):
        f = tmp_path / "clean.md"
        f.write_text("nothing to change\n")
        patterns = [("/old", "/new")]
        assert apply_memory_replacements(f, patterns) == 0
        assert f.read_text() == "nothing to change\n"

    def test_multiple_replacements_per_line(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("see /old/path and also /old/path here\n")
        patterns = [("/old/path", "/new/path")]
        changed = apply_memory_replacements(f, patterns)
        assert changed == 1
        assert f.read_text() == "see /new/path and also /new/path here\n"


# --- Interactive prompts ---


class TestPrompt3rdparty:
    def test_auto_yes_returns_3rdparty(self):
        assert prompt_3rdparty("microsoft", auto_yes=True) == "3rdParty"

    def test_non_tty_returns_3rdparty(self):
        assert prompt_3rdparty("unknown-owner") == "3rdParty"


# --- Integration: main() ---


def _make_git_repo(tmp_path, name, remote_url="git-test:TestOwner/repo.git"):
    repo = tmp_path / name
    repo.mkdir(parents=True)
    git_dir = repo / ".git"
    git_dir.mkdir()
    config = git_dir / "config"
    config.write_text(f'[remote "origin"]\n\turl = {remote_url}\n')
    return repo


def _make_ssh_config(tmp_path, content="Host git-test\n    HostName github.com\n"):
    config = tmp_path / "config.local"
    config.write_text(content)
    return config


def _make_claude_project(projects_dir, encoded_name, memory_files=None, sessions=0):
    d = projects_dir / encoded_name
    d.mkdir(parents=True, exist_ok=True)
    if memory_files:
        mem = d / "memory"
        mem.mkdir(exist_ok=True)
        for name, content in memory_files.items():
            (mem / name).write_text(content)
    for i in range(sessions):
        (d / f"session-{i}.jsonl").write_text('{"type":"user"}\n')
    return d


class TestMainDryRun:
    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    @patch("migrate_project.get_os_root")
    @patch("migrate_project.parse_ssh_aliases")
    def test_dry_run_shows_plan(
        self, mock_aliases, mock_root, mock_url, mock_toplevel, tmp_path, capsys
    ):
        repo = _make_git_repo(tmp_path / "Scaffoldings", "myrepo")
        target_root = tmp_path / "root"
        target_root.mkdir()

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = "git-test:TestOwner/myrepo.git"
        mock_root.return_value = target_root
        mock_aliases.return_value = {"git-test"}

        result = main(["--dry-run", str(repo)])

        assert result == 0
        output = capsys.readouterr().out
        assert "Migration plan" in output
        assert "DRY RUN" in output
        assert "TestOwner" in output

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    @patch("migrate_project.get_os_root")
    @patch("migrate_project.parse_ssh_aliases")
    def test_already_in_correct_location(
        self, mock_aliases, mock_root, mock_url, mock_toplevel, tmp_path, capsys
    ):
        root = tmp_path / "root"
        repo = root / "TestOwner" / "myrepo"
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = "git-test:TestOwner/myrepo.git"
        mock_root.return_value = root
        mock_aliases.return_value = {"git-test"}

        result = main(["--dry-run", str(repo)])

        assert result == 0
        output = capsys.readouterr().out
        assert "Already in correct location" in output

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    def test_not_a_directory(self, mock_url, mock_toplevel, tmp_path, capsys):
        result = main(["--dry-run", str(tmp_path / "nonexistent")])

        assert result == 1
        assert "not a directory" in capsys.readouterr().err

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    def test_not_a_git_repo(self, mock_url, mock_toplevel, tmp_path, capsys):
        d = tmp_path / "notgit"
        d.mkdir()

        result = main(["--dry-run", str(d)])

        assert result == 1
        assert "not a git repository" in capsys.readouterr().err

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    def test_no_origin_remote(self, mock_url, mock_toplevel, tmp_path, capsys):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = None

        result = main(["--dry-run", str(repo)])

        assert result == 1
        assert "no origin remote" in capsys.readouterr().err

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    def test_unparseable_remote(self, mock_url, mock_toplevel, tmp_path, capsys):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = "not-a-valid-url"

        result = main(["--dry-run", str(repo)])

        assert result == 1
        assert "cannot parse remote URL" in capsys.readouterr().err

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    def test_subdirectory_rejected(self, mock_url, mock_toplevel, tmp_path, capsys):
        repo = tmp_path / "myrepo"
        subdir = repo / "src"
        subdir.mkdir(parents=True)
        (subdir / ".git").write_text("gitdir: ../git")

        mock_toplevel.return_value = str(repo)

        result = main(["--dry-run", str(subdir)])

        assert result == 1
        assert "subdirectory" in capsys.readouterr().err

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    @patch("migrate_project.get_os_root")
    @patch("migrate_project.parse_ssh_aliases")
    def test_target_exists_and_nonempty(
        self, mock_aliases, mock_root, mock_url, mock_toplevel, tmp_path, capsys
    ):
        repo = _make_git_repo(tmp_path / "old", "myrepo")
        root = tmp_path / "root"
        target = root / "TestOwner" / "myrepo"
        target.mkdir(parents=True)
        (target / "somefile").write_text("blocking")

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = "git-test:TestOwner/myrepo.git"
        mock_root.return_value = root
        mock_aliases.return_value = {"git-test"}

        result = main(["--dry-run", str(repo)])

        assert result == 1
        assert "already exists" in capsys.readouterr().err


class TestMainExecute:
    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    @patch("migrate_project.get_os_root")
    @patch("migrate_project.parse_ssh_aliases")
    @patch("migrate_project.Path.home")
    def test_full_migration(
        self,
        mock_home,
        mock_aliases,
        mock_root,
        mock_url,
        mock_toplevel,
        tmp_path,
        capsys,
    ):
        mock_home.return_value = tmp_path

        old_root = tmp_path / "old"
        repo = _make_git_repo(old_root, "myrepo")
        (repo / "README.md").write_text("# My Repo")

        new_root = tmp_path / "root"
        new_root.mkdir()

        old_abs = str(repo)
        old_encoded = encode_path(old_abs)
        projects_dir = tmp_path / ".claude" / "projects"
        _make_claude_project(
            projects_dir,
            old_encoded,
            memory_files={"note.md": f"path: {old_abs}\n"},
            sessions=2,
        )

        mock_toplevel.return_value = old_abs
        mock_url.return_value = "git-test:TestOwner/myrepo.git"
        mock_root.return_value = new_root
        mock_aliases.return_value = {"git-test"}

        result = main(["--yes", str(repo)])

        assert result == 0
        new_repo = new_root / "TestOwner" / "myrepo"
        assert new_repo.is_dir()
        assert (new_repo / "README.md").read_text() == "# My Repo"
        assert not repo.exists()

        new_encoded = encode_path(str(new_repo))
        assert (projects_dir / new_encoded).is_dir()
        assert not (projects_dir / old_encoded).exists()

        note = (projects_dir / new_encoded / "memory" / "note.md").read_text()
        assert str(new_repo) in note
        assert old_abs not in note

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    @patch("migrate_project.get_os_root")
    @patch("migrate_project.parse_ssh_aliases")
    def test_3rdparty_with_yes_flag(
        self, mock_aliases, mock_root, mock_url, mock_toplevel, tmp_path, capsys
    ):
        repo = _make_git_repo(
            tmp_path / "old", "markitdown", "git@github.com:microsoft/markitdown.git"
        )

        root = tmp_path / "root"
        root.mkdir()

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = "git@github.com:microsoft/markitdown.git"
        mock_root.return_value = root
        mock_aliases.return_value = {"git-test"}

        result = main(["--dry-run", "--yes", str(repo)])

        assert result == 0
        output = capsys.readouterr().out
        assert "3rdParty" in output

    @patch("migrate_project.get_repo_toplevel")
    @patch("migrate_project.get_origin_url")
    @patch("migrate_project.get_os_root")
    @patch("migrate_project.parse_ssh_aliases")
    def test_dry_run_does_not_move(
        self, mock_aliases, mock_root, mock_url, mock_toplevel, tmp_path, capsys
    ):
        repo = _make_git_repo(tmp_path / "old", "myrepo")
        root = tmp_path / "root"
        root.mkdir()

        mock_toplevel.return_value = str(repo)
        mock_url.return_value = "git-test:TestOwner/myrepo.git"
        mock_root.return_value = root
        mock_aliases.return_value = {"git-test"}

        main(["--dry-run", str(repo)])

        assert repo.is_dir()
        assert not (root / "TestOwner" / "myrepo").exists()
