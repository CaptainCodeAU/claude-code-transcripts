# /// script
# requires-python = ">=3.10"
# ///
"""Migrate a repo to its correct username-based directory and update all
Claude Code project directories, memory files, and transcript archive
folders to match.

Run via: uv run python scripts/migrate_project.py <path>
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from claude_code_transcripts import get_project_display_name

# ---------------------------------------------------------------------------
# Path encoding (same as Claude Code's internal encoding)
# ---------------------------------------------------------------------------


def encode_path(absolute_path: str) -> str:
    return absolute_path.replace("/", "-").replace("_", "-").replace(".", "-")


def tilde_form(absolute_path: str) -> str:
    home = str(Path.home())
    if absolute_path.startswith(home):
        return "~" + absolute_path[len(home) :]
    return absolute_path


def display_tilde(path: Path) -> str:
    home = str(Path.home())
    s = str(path)
    if s.startswith(home):
        return "~" + s[len(home) :]
    return s


# ---------------------------------------------------------------------------
# Git remote parsing
# ---------------------------------------------------------------------------

REMOTE_RE = re.compile(
    r"^(?:"
    r"https?://([\w.-]+)/([\w./-]+)"  # HTTPS: https://host/owner/repo
    r"|"
    r"(?:[\w.-]+@)?([\w.-]+):([\w./-]+)"  # SSH: [user@]host:owner/repo
    r")$"
)


def parse_remote_url(url: str) -> tuple[str, str, str] | None:
    """Parse a git remote URL into (host, owner, repo).

    Returns None if the URL cannot be parsed.
    """
    m = REMOTE_RE.match(url.strip())
    if not m:
        return None
    if m.group(1):
        host = m.group(1)
        path = m.group(2)
    else:
        host = m.group(3)
        path = m.group(4)
    parts = path.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    return host, owner, repo


def get_origin_url(repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_repo_toplevel(repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# ---------------------------------------------------------------------------
# SSH config parsing
# ---------------------------------------------------------------------------


def parse_ssh_aliases(config_path: Path | None = None) -> set[str]:
    """Parse ~/.ssh/config.local for Host git-* entries.

    Returns a set of alias hostnames like {'git-acme', 'git-other'}.
    """
    if config_path is None:
        config_path = Path.home() / ".ssh" / "config.local"
    aliases: set[str] = set()
    if not config_path.is_file():
        return aliases
    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return aliases
    for line in content.splitlines():
        line = line.strip()
        if line.lower().startswith("host ") and not line.startswith("Host *"):
            for name in line.split()[1:]:
                if name.startswith("git-"):
                    aliases.add(name)
    return aliases


# ---------------------------------------------------------------------------
# OS root detection
# ---------------------------------------------------------------------------


def get_os_root() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "CODE"
    return Path.home() / "repos"


# ---------------------------------------------------------------------------
# Claude project directory scanning
# ---------------------------------------------------------------------------


def find_matching_directories(projects_dir: Path, old_encoded: str) -> list[Path]:
    if not projects_dir.is_dir():
        return []
    matches = []
    for entry in sorted(projects_dir.iterdir()):
        if entry.is_dir() and entry.name.startswith(old_encoded):
            rest = entry.name[len(old_encoded) :]
            if rest == "" or rest.startswith("-"):
                matches.append(entry)
    return matches


def count_contents(directory: Path) -> tuple[int, int]:
    memory_count = 0
    session_count = 0
    memory_dir = directory / "memory"
    if memory_dir.is_dir():
        for f in memory_dir.rglob("*"):
            if f.is_file():
                memory_count += 1
    for f in directory.iterdir():
        if f.is_file() and f.suffix == ".jsonl":
            session_count += 1
    return memory_count, session_count


# ---------------------------------------------------------------------------
# Memory file scanning and replacement
# ---------------------------------------------------------------------------


def scan_memory_files(
    directory: Path,
    search_patterns: list[tuple[str, str]],
) -> list[tuple[Path, int]]:
    """Scan memory files for path references. Returns list of (path, match_count)."""
    memory_dir = directory / "memory"
    if not memory_dir.is_dir():
        return []
    results = []
    for filepath in sorted(memory_dir.rglob("*")):
        if not filepath.is_file():
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        match_count = 0
        for old_str, _ in search_patterns:
            match_count += content.count(old_str)
        if match_count > 0:
            results.append((filepath, match_count))
    return results


def apply_memory_replacements(
    filepath: Path, search_patterns: list[tuple[str, str]]
) -> int:
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    new_content = content
    for old_str, new_str in search_patterns:
        new_content = new_content.replace(old_str, new_str)
    if new_content != content:
        filepath.write_text(new_content, encoding="utf-8")
        return sum(
            1
            for old_line, new_line in zip(
                content.splitlines(), new_content.splitlines()
            )
            if old_line != new_line
        )
    return 0


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def confirm(prompt: str, auto_yes: bool = False) -> bool:
    if auto_yes:
        return True
    if not sys.stdin.isatty():
        return True
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def prompt_3rdparty(owner: str, auto_yes: bool = False) -> str:
    """Prompt user for the subfolder when the owner is not a known account."""
    if auto_yes:
        return "3rdParty"
    if not sys.stdin.isatty():
        return "3rdParty"
    print(f"\n  Owner {BOLD}{owner}{RESET} is not a known account.")
    try:
        answer = input(
            f"  Move to {BOLD}3rdParty/{RESET}? [Y/n/custom folder name] "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    if not answer or answer.lower() in ("y", "yes"):
        return "3rdParty"
    if answer.lower() in ("n", "no"):
        print("  Aborted.", file=sys.stderr)
        sys.exit(1)
    return answer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate a repo to its correct username-based directory.",
        epilog=(
            "Examples:\n"
            "  %(prog)s ~/CODE/Legacy/my-project\n"
            "  %(prog)s --dry-run ~/repos/my-app\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project_path",
        metavar="PATH",
        help="Path to the project to migrate.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show migration plan without executing or prompting.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmations.",
    )
    parser.add_argument(
        "--archive-path",
        metavar="PATH",
        help="Transcript archive directory. Defaults to ~/CODE/my-claude-code-transcripts/ on macOS.",
    )
    args = parser.parse_args(argv)

    # -- Step 1: Input validation --
    project_path = Path(os.path.expanduser(args.project_path)).resolve()
    if not project_path.is_dir():
        print(f"Error: {project_path} is not a directory.", file=sys.stderr)
        return 1
    if not (project_path / ".git").exists():
        print(f"Error: {project_path} is not a git repository.", file=sys.stderr)
        return 1
    toplevel = get_repo_toplevel(str(project_path))
    if toplevel and Path(toplevel).resolve() != project_path:
        print(
            f"Error: {project_path} is a subdirectory, not the repo root.\n"
            f"  Repo root is: {toplevel}",
            file=sys.stderr,
        )
        return 1

    old_abs = str(project_path)

    # -- Step 2: Extract GitHub owner from git remote --
    url = get_origin_url(old_abs)
    if not url:
        print("Error: no origin remote found.", file=sys.stderr)
        return 1
    parsed = parse_remote_url(url)
    if not parsed:
        print(f"Error: cannot parse remote URL: {url}", file=sys.stderr)
        return 1
    remote_host, owner, repo_name = parsed

    # -- Step 3: Classify own account or 3rdParty --
    ssh_aliases = parse_ssh_aliases()
    if remote_host in ssh_aliases:
        subfolder = owner
    elif remote_host == "github.com":
        subfolder = prompt_3rdparty(owner, args.yes)
    else:
        subfolder = prompt_3rdparty(owner, args.yes)

    # -- Step 4: Compute target path --
    os_root = get_os_root()
    repo_folder_name = project_path.name
    target_path = os_root / subfolder / repo_folder_name
    new_abs = str(target_path)

    if Path(old_abs).resolve() == target_path.resolve():
        print(
            f"{GREEN}Already in correct location:{RESET} {display_tilde(project_path)}"
        )
        return 0
    if target_path.exists() and any(target_path.iterdir()):
        print(
            f"Error: target directory already exists and is not empty:\n"
            f"  {display_tilde(target_path)}",
            file=sys.stderr,
        )
        return 1

    # -- Step 5: Compute Claude project directory renames --
    old_encoded = encode_path(old_abs)
    new_encoded = encode_path(new_abs)
    projects_dir = Path.home() / ".claude" / "projects"
    claude_matches = find_matching_directories(projects_dir, old_encoded)

    renames: list[tuple[Path, Path, int, int]] = []
    for old_dir in claude_matches:
        rest = old_dir.name[len(old_encoded) :]
        new_name = new_encoded + rest
        new_dir = projects_dir / new_name
        mem_count, sess_count = count_contents(old_dir)
        renames.append((old_dir, new_dir, mem_count, sess_count))

    # -- Step 6: Scan memory files for path references --
    old_tilde = tilde_form(old_abs)
    new_tilde = tilde_form(new_abs)
    search_patterns: list[tuple[str, str]] = [
        (old_abs, new_abs),
    ]
    if old_tilde != old_abs:
        search_patterns.append((old_tilde, new_tilde))
    search_patterns.append((old_encoded, new_encoded))

    memory_files: list[tuple[Path, int]] = []
    for old_dir in claude_matches:
        memory_files.extend(scan_memory_files(old_dir, search_patterns))

    # -- Step 7: Compute transcript archive rename --
    archive_path = None
    archive_rename: tuple[Path, Path] | None = None

    if args.archive_path:
        archive_path = Path(os.path.expanduser(args.archive_path)).resolve()
    elif platform.system() == "Darwin":
        default_archive = Path.home() / "CODE" / "my-claude-code-transcripts"
        if default_archive.is_dir():
            archive_path = default_archive

    if archive_path:
        old_display = get_project_display_name(old_encoded)
        new_display = get_project_display_name(new_encoded)
        if old_display != new_display:
            old_archive_dir = archive_path / old_display
            new_archive_dir = archive_path / new_display
            if old_archive_dir.is_dir():
                archive_rename = (old_archive_dir, new_archive_dir)

    # -- Step 8: Display migration plan --
    print(f"\n{BOLD}Migration plan for:{RESET} {CYAN}{repo_folder_name}{RESET}\n")
    print(f"  {BOLD}Repo move:{RESET}")
    print(f"    {DIM}{display_tilde(project_path)}{RESET}")
    print(f"    -> {BOLD}{display_tilde(target_path)}{RESET}")

    if renames:
        print(
            f"\n  {BOLD}Claude project directories:{RESET} {CYAN}{len(renames)}{RESET} to rename"
        )
        for old_dir, new_dir, mem_count, sess_count in renames:
            suffix = old_dir.name[len(old_encoded) :]
            print(f"    {DIM}{old_dir.name}{RESET}")
            print(f"    -> {BOLD}{new_encoded}{suffix}{RESET}")
            print(
                f"    {DIM}({mem_count} memory files, {sess_count} session logs){RESET}"
            )
    else:
        print(f"\n  {BOLD}Claude project directories:{RESET} {DIM}none found{RESET}")

    if memory_files:
        total_refs = sum(c for _, c in memory_files)
        print(
            f"\n  {BOLD}Memory file updates:{RESET} {CYAN}{len(memory_files)}{RESET} files with {CYAN}{total_refs}{RESET} path references"
        )
    else:
        print(f"\n  {BOLD}Memory file updates:{RESET} {DIM}none{RESET}")

    if archive_rename:
        old_ad, new_ad = archive_rename
        print(f"\n  {BOLD}Archive folder rename:{RESET}")
        print(f"    {DIM}{old_ad.name}/{RESET}")
        print(f"    -> {BOLD}{new_ad.name}/{RESET}")
    elif archive_path:
        print(f"\n  {BOLD}Archive folder rename:{RESET} {DIM}not needed{RESET}")

    print()

    if args.dry_run:
        print(f"{YELLOW}DRY RUN{RESET} -- no changes made.")
        return 0

    if not confirm("Proceed?", args.yes):
        print("  Aborted.")
        return 0

    # -- Step 9: Execute --
    print()

    # 9a. Create target parent directory
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # 9b. Move the repo folder
    if target_path.exists():
        try:
            target_path.rmdir()
        except OSError:
            print(
                f"Error: could not remove non-empty target {display_tilde(target_path)}",
                file=sys.stderr,
            )
            return 1
    shutil.move(str(project_path), str(target_path))
    print(f"  {GREEN}Moved repo{RESET} -> {display_tilde(target_path)}")

    # 9c. Update memory file contents (before renames, while paths are stable)
    files_modified = 0
    for old_dir in claude_matches:
        memory_dir = old_dir / "memory"
        if not memory_dir.is_dir():
            continue
        for filepath in sorted(memory_dir.rglob("*")):
            if not filepath.is_file():
                continue
            changed = apply_memory_replacements(filepath, search_patterns)
            if changed > 0:
                files_modified += 1

    if files_modified:
        print(f"  {GREEN}Updated{RESET} {files_modified} memory files")

    # 9d. Rename Claude project directories
    dirs_renamed = 0
    for old_dir, new_dir, _, _ in renames:
        if new_dir.exists():
            try:
                new_dir.rmdir()
            except OSError:
                print(
                    f"  {RED}Error:{RESET} could not remove {display_tilde(new_dir)}",
                    file=sys.stderr,
                )
                continue
        old_dir.rename(new_dir)
        dirs_renamed += 1

    if dirs_renamed:
        print(f"  {GREEN}Renamed{RESET} {dirs_renamed} Claude project directories")

    # 9e. Rename transcript archive folder
    if archive_rename:
        old_ad, new_ad = archive_rename
        if new_ad.exists():
            try:
                new_ad.rmdir()
            except OSError:
                print(
                    f"  {RED}Error:{RESET} archive target {new_ad.name} exists and is not empty",
                    file=sys.stderr,
                )
                archive_rename = None
        if archive_rename:
            old_ad.rename(new_ad)
            print(f"  {GREEN}Renamed archive{RESET} -> {new_ad.name}/")

    # -- Step 10: Summary --
    print(f"\n{BOLD}Done.{RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
