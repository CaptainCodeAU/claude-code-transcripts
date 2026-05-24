# /// script
# requires-python = ">=3.10"
# ///
"""Reconcile orphan Claude Code session folders into project directories.

Run via: uv run python scripts/reconcile_sessions.py <path>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from claude_code_transcripts import get_project_display_name, get_session_summary

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile orphan Claude Code session folders into project directories.",
        epilog=(
            "Examples:\n"
            "  %(prog)s ~/CODE/my-claude-code-transcripts/\n"
            "  %(prog)s --dry-run ~/CODE/my-claude-code-transcripts/\n"
            "  %(prog)s --no-reindex ~/CODE/my-claude-code-transcripts/\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        metavar="PATH",
        help="Path to the transcript archive directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )
    parser.add_argument(
        "--no-reindex",
        action="store_true",
        help="Skip rebuilding project and master index.html pages after reconciliation.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmations.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete verified duplicate and empty orphan folders after reconciliation.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed error output on failures.",
    )
    return parser.parse_args(argv)


def extract_cwd_from_jsonl(jsonl_path: Path) -> str | None:
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    cwd = obj.get("cwd", "")
                    if cwd:
                        return cwd
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, OSError):
        return None
    return None


def cwd_to_project_name(cwd: str) -> str:
    encoded = cwd.replace("/", "-").replace("_", "-").replace(".", "-")
    return get_project_display_name(encoded)


class Category(Enum):
    A_JSONL = auto()
    B_HTML_ONLY = auto()
    C_EMPTY = auto()
    D_OTHER = auto()


@dataclass
class CategorizedFolder:
    path: Path
    category: Category
    jsonl_path: Path | None = None
    html_files: list[Path] = field(default_factory=list)
    cwd: str | None = None
    target_project: str | None = None


def categorize_folder(folder: Path) -> CategorizedFolder:
    jsonl_files = list(folder.glob("*.jsonl"))
    html_files = list(folder.glob("*.html"))
    all_files = list(folder.iterdir())

    if jsonl_files:
        preferred = folder / f"{folder.name}.jsonl"
        chosen_jsonl = preferred if preferred in jsonl_files else jsonl_files[0]
        cwd = extract_cwd_from_jsonl(chosen_jsonl)
        return CategorizedFolder(
            path=folder,
            category=Category.A_JSONL,
            jsonl_path=chosen_jsonl,
            html_files=html_files,
            cwd=cwd,
        )

    if html_files:
        return CategorizedFolder(
            path=folder,
            category=Category.B_HTML_ONLY,
            html_files=html_files,
        )

    if not all_files:
        return CategorizedFolder(path=folder, category=Category.C_EMPTY)

    return CategorizedFolder(path=folder, category=Category.D_OTHER)


def categorize_all(
    uuid_folders: list[Path],
) -> dict[Category, list[CategorizedFolder]]:
    result: dict[Category, list[CategorizedFolder]] = {c: [] for c in Category}
    for folder in uuid_folders:
        cat = categorize_folder(folder)
        result[cat.category].append(cat)
    return result


def find_matching_project(
    derived_name: str, existing_projects: list[str]
) -> str | None:
    lower = derived_name.lower()
    for proj in existing_projects:
        if proj.lower() == lower:
            return proj
    return None


def resolve_target_project(cwd: str, existing_projects: list[str]) -> tuple[str, bool]:
    derived = cwd_to_project_name(cwd)
    match = find_matching_project(derived, existing_projects)
    if match:
        return match, False
    return derived, True


CWD_PATH_RE = re.compile(
    r"/(?:Users|home)/[^\s<>\"']+?/(?:CODE|code|projects|repos)/[^\s<>\"']+"
)

FILE_EXT_RE = re.compile(r"\.[a-zA-Z0-9]{1,5}$")


def extract_project_from_html(html_path: Path) -> str | None:
    try:
        content = html_path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return None

    matches = CWD_PATH_RE.findall(content)
    if not matches:
        return None

    path = matches[0].rstrip("</\"'")
    parts = path.split("/")
    # Reconstruct up to the project dir (skip file at end if it has an extension)
    if FILE_EXT_RE.search(parts[-1]):
        parts = parts[:-1]
    cwd = "/".join(parts)
    return cwd_to_project_name(cwd)


UNKNOWN_PROJECT = "unknown-project"


@dataclass
class MoveResult:
    uuid: str
    source: Path
    target_project: str
    success: bool
    error: str = ""
    regenerated: bool = False
    regen_failed: bool = False
    is_new_project: bool = False
    is_duplicate: bool = False
    is_unknown: bool = False
    replaced_organized: bool = False


def list_existing_projects(archive_path: Path) -> list[str]:
    result = []
    for entry in archive_path.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        if UUID_PATTERN.match(entry.name):
            continue
        result.append(entry.name)
    result.sort()
    return result


def _find_jsonl_in_dir(d: Path) -> Path | None:
    preferred = d / f"{d.name}.jsonl"
    if preferred.exists():
        return preferred
    jsonl_files = list(d.glob("*.jsonl"))
    return jsonl_files[0] if jsonl_files else None


def compare_session_copies(orphan_dir: Path, organized_dir: Path) -> tuple[str, str]:
    orphan_jsonl = _find_jsonl_in_dir(orphan_dir)
    organized_jsonl = _find_jsonl_in_dir(organized_dir)

    if orphan_jsonl and organized_jsonl:
        try:
            orphan_size = orphan_jsonl.stat().st_size
            organized_size = organized_jsonl.stat().st_size
        except OSError:
            return "identical", "stat failed"
        if orphan_size > organized_size:
            return "orphan", f"JSONL {orphan_size} > {organized_size} bytes"
        if organized_size > orphan_size:
            return "organized", f"JSONL {organized_size} > {orphan_size} bytes"
        return "identical", f"JSONL sizes match ({orphan_size} bytes)"

    if orphan_jsonl and not organized_jsonl:
        return "orphan", "only orphan has JSONL"
    if organized_jsonl and not orphan_jsonl:
        return "organized", "only organized has JSONL"

    try:
        orphan_mtime = max(
            (f.stat().st_mtime for f in orphan_dir.iterdir() if f.is_file()),
            default=0,
        )
        organized_mtime = max(
            (f.stat().st_mtime for f in organized_dir.iterdir() if f.is_file()),
            default=0,
        )
    except OSError:
        return "identical", "stat failed"

    if orphan_mtime > organized_mtime + 60:
        return "orphan", "newer files by mtime"
    if organized_mtime > orphan_mtime + 60:
        return "organized", "newer files by mtime"
    return "identical", "similar mtimes"


def _is_session_dir(d: Path) -> bool:
    if UUID_PATTERN.match(d.name):
        return True
    return any(d.glob("*.jsonl")) or any(d.glob("*.html"))


def _handle_duplicate(
    uuid: str,
    folder: CategorizedFolder,
    target_name: str,
    target_dir: Path,
    archive_path: Path,
    existing_projects: list[str],
    dry_run: bool,
    verbose: bool,
    is_unknown: bool = False,
) -> tuple[MoveResult | None, bool]:
    """Handle the case where target_dir already exists.

    Returns (MoveResult, replaced) where:
    - (MoveResult, False): duplicate resolved, caller should return this result
    - (None, True): organized copy deleted, caller should proceed with move and mark replaced
    - (None, False): target doesn't exist, caller should proceed normally
    """
    if not target_dir.exists():
        return None, False

    winner, reason = compare_session_copies(folder.path, target_dir)

    if winner == "orphan":
        if dry_run:
            return (
                MoveResult(
                    uuid=uuid,
                    source=folder.path,
                    target_project=target_name,
                    success=True,
                    replaced_organized=True,
                    is_unknown=is_unknown,
                ),
                True,
            )
        shutil.rmtree(str(target_dir))
        return None, True

    return (
        MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=True,
            is_duplicate=True,
            is_unknown=is_unknown,
        ),
        False,
    )


def process_category_a(
    folder: CategorizedFolder,
    archive_path: Path,
    existing_projects: list[str],
    dry_run: bool,
    verbose: bool = False,
) -> MoveResult:
    uuid = folder.path.name

    if not folder.cwd:
        target_name = UNKNOWN_PROJECT
        is_new = target_name not in existing_projects
        is_unknown = True
    else:
        target_name, is_new = resolve_target_project(folder.cwd, existing_projects)
        is_unknown = False

    target_dir = archive_path / target_name / uuid

    dup_result, is_replacing = _handle_duplicate(
        uuid,
        folder,
        target_name,
        target_dir,
        archive_path,
        existing_projects,
        dry_run,
        verbose,
        is_unknown,
    )
    if dup_result is not None:
        return dup_result

    if dry_run:
        return MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=True,
            is_new_project=is_new,
            is_unknown=is_unknown,
        )

    try:
        (archive_path / target_name).mkdir(exist_ok=True)
        if is_new and target_name not in existing_projects:
            existing_projects.append(target_name)

        regenerated = False
        regen_failed = False
        if folder.jsonl_path and folder.jsonl_path.exists() and not is_unknown:
            try:
                result = subprocess.run(
                    [
                        "uv",
                        "run",
                        "claude-code-transcripts",
                        "json",
                        str(folder.jsonl_path),
                        "-o",
                        str(folder.path),
                        "--no-json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                regenerated = result.returncode == 0
                if not regenerated:
                    regen_failed = True
                    if verbose:
                        print(
                            f"\n    {YELLOW}Regen failed for {uuid}:{RESET}\n    {result.stderr.strip()}"
                        )
            except (subprocess.TimeoutExpired, OSError) as e:
                regen_failed = True
                if verbose:
                    print(f"\n    {YELLOW}Regen error for {uuid}:{RESET} {e}")

        shutil.move(str(folder.path), str(target_dir))
        return MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=True,
            regenerated=regenerated,
            regen_failed=regen_failed,
            is_new_project=is_new,
            is_unknown=is_unknown,
            replaced_organized=is_replacing,
        )
    except OSError as e:
        return MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=False,
            error=str(e),
            is_unknown=is_unknown,
        )


def process_category_b(
    folder: CategorizedFolder,
    archive_path: Path,
    existing_projects: list[str],
    dry_run: bool,
    verbose: bool = False,
) -> MoveResult:
    uuid = folder.path.name

    project_name = None
    for html_file in folder.html_files:
        project_name = extract_project_from_html(html_file)
        if project_name:
            break

    if not project_name:
        target_name = UNKNOWN_PROJECT
        is_new = target_name not in existing_projects
        is_unknown = True
    else:
        match = find_matching_project(project_name, existing_projects)
        is_new = match is None
        target_name = match or project_name
        is_unknown = False

    target_dir = archive_path / target_name / uuid

    dup_result, is_replacing = _handle_duplicate(
        uuid,
        folder,
        target_name,
        target_dir,
        archive_path,
        existing_projects,
        dry_run,
        verbose,
        is_unknown,
    )
    if dup_result is not None:
        return dup_result

    if dry_run:
        return MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=True,
            is_new_project=is_new,
            is_unknown=is_unknown,
        )

    try:
        (archive_path / target_name).mkdir(exist_ok=True)
        if is_new and target_name not in existing_projects:
            existing_projects.append(target_name)
        shutil.move(str(folder.path), str(target_dir))
        return MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=True,
            is_new_project=is_new,
            is_unknown=is_unknown,
            replaced_organized=is_replacing,
        )
    except OSError as e:
        return MoveResult(
            uuid=uuid,
            source=folder.path,
            target_project=target_name,
            success=False,
            error=str(e),
            is_unknown=is_unknown,
        )


def scan_archive_for_projects(archive_path: Path) -> list[dict]:
    projects = []
    for entry in sorted(archive_path.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if entry.name.startswith("."):
            continue
        if UUID_PATTERN.match(entry.name):
            continue

        sessions = []
        for session_dir in sorted(entry.iterdir(), key=lambda p: p.name):
            if not session_dir.is_dir():
                continue
            if not _is_session_dir(session_dir):
                continue

            jsonl = session_dir / f"{session_dir.name}.jsonl"
            if jsonl.exists():
                try:
                    summary = get_session_summary(jsonl)
                    stat = jsonl.stat()
                    sessions.append(
                        {
                            "path": jsonl,
                            "summary": summary,
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                        }
                    )
                except OSError:
                    continue
            else:
                index_html = session_dir / "index.html"
                if index_html.exists():
                    try:
                        stat = index_html.stat()
                        synthetic_path = session_dir / f"{session_dir.name}.jsonl"
                        sessions.append(
                            {
                                "path": synthetic_path,
                                "summary": "(HTML only)",
                                "mtime": stat.st_mtime,
                                "size": stat.st_size,
                            }
                        )
                    except OSError:
                        continue

        sessions.sort(key=lambda s: s["mtime"], reverse=True)
        projects.append({"name": entry.name, "path": entry, "sessions": sessions})

    projects.sort(
        key=lambda p: p["sessions"][0]["mtime"] if p["sessions"] else 0,
        reverse=True,
    )
    return projects


def find_uuid_folders(archive_path: Path) -> list[Path]:
    result = []
    for entry in archive_path.iterdir():
        if entry.is_symlink():
            continue
        if entry.is_dir() and UUID_PATTERN.match(entry.name):
            result.append(entry)
    result.sort(key=lambda p: p.name)
    return result


@dataclass
class ReconciliationReport:
    moved_jsonl: int = 0
    moved_html: int = 0
    moved_unknown: int = 0
    replaced: int = 0
    already_organized: int = 0
    skipped_empty: int = 0
    failed: int = 0
    cleaned_duplicates: int = 0
    cleaned_empty: int = 0
    new_projects: list[str] = field(default_factory=list)
    outliers: list[tuple[str, str]] = field(default_factory=list)
    duplicate_paths: list[Path] = field(default_factory=list)
    empty_paths: list[Path] = field(default_factory=list)
    projects_affected: set[str] = field(default_factory=set)
    reindexed: bool = False
    elapsed_seconds: float = 0.0


CATEGORY_LABELS = {
    Category.A_JSONL: "Has JSONL (can regenerate HTML)",
    Category.B_HTML_ONLY: "HTML only (no JSONL)",
    Category.C_EMPTY: "Empty folder",
    Category.D_OTHER: "Other/unexpected content",
}


def format_category_table(categories: dict[Category, list]) -> str:
    lines = [
        f"{BOLD}{'Category':<40} {'Count':>6}{RESET}",
        f"{'':=<47}",
    ]
    for cat in Category:
        label = CATEGORY_LABELS[cat]
        count = len(categories[cat])
        color = GREEN if count == 0 else CYAN
        lines.append(f"  {label:<38} {color}{count:>6}{RESET}")
    total = sum(len(v) for v in categories.values())
    lines.append(f"{'':=<47}")
    lines.append(f"  {'Total':<38} {BOLD}{total:>6}{RESET}")
    return "\n".join(lines)


def format_report(report: ReconciliationReport) -> str:
    total = (
        report.moved_jsonl
        + report.moved_html
        + report.moved_unknown
        + report.replaced
        + report.already_organized
        + report.skipped_empty
        + report.failed
    )
    lines = [
        "",
        f"{BOLD}=== RECONCILIATION REPORT ==={RESET}",
        "",
        f"  Processed: {CYAN}{total}{RESET} session folders",
        f"    Moved (with JSONL):    {GREEN}{report.moved_jsonl:>4}{RESET}",
        f"    Moved (HTML only):     {GREEN}{report.moved_html:>4}{RESET}",
        f"    Moved (unknown):       {YELLOW}{report.moved_unknown:>4}{RESET}",
        f"    Replaced (newer):      {CYAN}{report.replaced:>4}{RESET}",
        f"    Already organized:     {CYAN}{report.already_organized:>4}{RESET}",
        f"    Skipped (empty):       {YELLOW}{report.skipped_empty:>4}{RESET}",
        f"    Failed:                {RED}{report.failed:>4}{RESET}",
        "",
        f"  Projects affected: {CYAN}{len(report.projects_affected)}{RESET}",
    ]
    if report.new_projects:
        lines.append(
            f"    New projects created: {GREEN}{len(report.new_projects)}{RESET}"
        )
        for name in report.new_projects:
            lines.append(f"      - {name}")

    if report.outliers:
        lines.append("")
        lines.append(f"  {YELLOW}Outliers & Issues:{RESET}")
        for uuid, reason in report.outliers:
            lines.append(f"    - {uuid}: {reason}")

    if report.cleaned_duplicates or report.cleaned_empty:
        lines.append("")
        lines.append(f"  {BOLD}Cleanup:{RESET}")
        if report.cleaned_duplicates:
            lines.append(
                f"    Deleted duplicates:   {GREEN}{report.cleaned_duplicates:>4}{RESET}"
            )
        if report.cleaned_empty:
            lines.append(
                f"    Deleted empty:        {GREEN}{report.cleaned_empty:>4}{RESET}"
            )

    if report.elapsed_seconds > 0:
        lines.append(f"  Elapsed: {CYAN}{report.elapsed_seconds:.1f}s{RESET}")
    lines.append("")
    lines.append(
        f"  Reindex: {GREEN}completed{RESET}"
        if report.reindexed
        else f"  Reindex: {YELLOW}skipped{RESET}"
    )
    lines.append("")
    return "\n".join(lines)


def reindex_archive(archive_path: Path) -> None:
    from claude_code_transcripts import _generate_master_index, _generate_project_index

    projects = scan_archive_for_projects(archive_path)

    for project in projects:
        project_dir = archive_path / project["name"]
        _generate_project_index(project, project_dir)

    _generate_master_index(projects, archive_path)


def confirm(message: str, auto_yes: bool) -> bool:
    if auto_yes or not sys.stdin.isatty():
        return True
    try:
        response = input(f"{message} [y/N] ")
        return response.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _tally_result(
    result: MoveResult, report: ReconciliationReport, is_jsonl_category: bool
) -> None:
    if result.is_duplicate:
        report.already_organized += 1
        report.duplicate_paths.append(result.source)
        return
    if result.replaced_organized:
        report.replaced += 1
        report.projects_affected.add(result.target_project)
        return
    if not result.success:
        report.failed += 1
        report.outliers.append((result.uuid, result.error))
        return
    if result.is_unknown:
        report.moved_unknown += 1
    elif is_jsonl_category:
        report.moved_jsonl += 1
    else:
        report.moved_html += 1
    report.projects_affected.add(result.target_project)
    if result.is_new_project and result.target_project not in report.new_projects:
        report.new_projects.append(result.target_project)
    if result.regen_failed:
        report.outliers.append(
            (result.uuid, "Moved with stale HTML (regeneration failed)")
        )


def print_archive_summary(archive_path: Path) -> None:
    projects = scan_archive_for_projects(archive_path)
    total_sessions = sum(len(p["sessions"]) for p in projects)
    print(f"{BOLD}Archive:{RESET} {archive_path}")
    print(f"  Projects: {CYAN}{len(projects)}{RESET}")
    print(f"  Sessions: {CYAN}{total_sessions:,}{RESET}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    archive_path = Path(args.path).resolve()

    if not archive_path.is_dir():
        print(f"{RED}Error: {archive_path} is not a directory{RESET}", file=sys.stderr)
        sys.exit(1)

    print()
    print_archive_summary(archive_path)

    uuid_folders = find_uuid_folders(archive_path)

    if not uuid_folders and args.no_reindex:
        print(f"\n{GREEN}No orphan folders found. Archive is clean.{RESET}")
        sys.exit(0)

    if not uuid_folders:
        print(f"\n{GREEN}No orphan folders found. Archive is clean.{RESET}")

    report = ReconciliationReport()
    start_time = time.monotonic()
    is_tty = sys.stdout.isatty()

    if uuid_folders:
        print(
            f"\n{BOLD}Found {CYAN}{len(uuid_folders)}{RESET}{BOLD} orphan UUID folders{RESET}\n"
        )

        categories = categorize_all(uuid_folders)
        print(format_category_table(categories))
        print()

        if args.dry_run:
            print(f"{YELLOW}{BOLD}DRY RUN - no changes will be made{RESET}\n")

        if not confirm("Proceed with reconciliation?", args.yes):
            print("Aborted.")
            sys.exit(0)

        existing = list_existing_projects(archive_path)

        # Process Category A
        for i, folder in enumerate(categories[Category.A_JSONL], 1):
            count = len(categories[Category.A_JSONL])
            if is_tty:
                print(
                    f"\r  Processing JSONL {CYAN}{i}/{count}{RESET}: {folder.path.name}",
                    end="",
                    flush=True,
                )
            else:
                print(f"  Processing JSONL {i}/{count}: {folder.path.name}")
            result = process_category_a(
                folder, archive_path, existing, args.dry_run, verbose=args.verbose
            )
            _tally_result(result, report, is_jsonl_category=True)
            if args.dry_run and args.verbose:
                suffix = ""
                if result.is_new_project:
                    suffix += " [NEW]"
                if result.replaced_organized:
                    suffix += " [REPLACE]"
                if result.is_duplicate:
                    suffix += " [DUPLICATE]"
                if result.is_unknown:
                    suffix += " [UNKNOWN]"
                print(f"    {result.uuid} -> {result.target_project}{suffix}")
        if categories[Category.A_JSONL] and is_tty:
            print()

        # Process Category B
        for i, folder in enumerate(categories[Category.B_HTML_ONLY], 1):
            count = len(categories[Category.B_HTML_ONLY])
            if is_tty:
                print(
                    f"\r  Processing HTML {CYAN}{i}/{count}{RESET}: {folder.path.name}",
                    end="",
                    flush=True,
                )
            else:
                print(f"  Processing HTML {i}/{count}: {folder.path.name}")
            result = process_category_b(
                folder, archive_path, existing, args.dry_run, verbose=args.verbose
            )
            _tally_result(result, report, is_jsonl_category=False)
            if args.dry_run and args.verbose:
                suffix = ""
                if result.is_new_project:
                    suffix += " [NEW]"
                if result.replaced_organized:
                    suffix += " [REPLACE]"
                if result.is_duplicate:
                    suffix += " [DUPLICATE]"
                if result.is_unknown:
                    suffix += " [UNKNOWN]"
                print(f"    {result.uuid} -> {result.target_project}{suffix}")
        if categories[Category.B_HTML_ONLY] and is_tty:
            print()

        # Flag Category C + D
        for folder in categories[Category.C_EMPTY]:
            report.skipped_empty += 1
            report.empty_paths.append(folder.path)
            report.outliers.append((folder.path.name, "Empty folder"))

        for folder in categories[Category.D_OTHER]:
            report.failed += 1
            try:
                file_names = sorted(f.name for f in folder.path.iterdir())
                detail = ", ".join(file_names[:5])
                if len(file_names) > 5:
                    detail += f" (+{len(file_names) - 5} more)"
                report.outliers.append(
                    (folder.path.name, f"Unexpected content: {detail}")
                )
            except OSError:
                report.outliers.append(
                    (folder.path.name, "Unexpected content (unreadable)")
                )

    # Cleanup verified duplicates and empties
    if args.cleanup and not args.dry_run:
        to_delete = report.duplicate_paths + report.empty_paths
        if to_delete:
            print(
                f"\n{BOLD}Cleaning up {CYAN}{len(to_delete)}{RESET}{BOLD} verified duplicate/empty folders...{RESET}"
            )
            if confirm(
                f"Delete {len(to_delete)} folders? This cannot be undone.",
                args.yes,
            ):
                for p in to_delete:
                    try:
                        if p.exists():
                            shutil.rmtree(str(p))
                            if p in report.duplicate_paths:
                                report.cleaned_duplicates += 1
                            else:
                                report.cleaned_empty += 1
                    except OSError as e:
                        report.outliers.append((p.name, f"Cleanup failed: {e}"))
    elif args.cleanup and args.dry_run:
        count = len(report.duplicate_paths) + len(report.empty_paths)
        if count:
            print(
                f"\n{YELLOW}--cleanup with --dry-run: would delete {count} folders{RESET}"
            )

    # Reindex (default unless --no-reindex)
    if not args.no_reindex:
        print(f"\n{BOLD}Rebuilding indexes...{RESET}")
        try:
            reindex_archive(archive_path)
            report.reindexed = True
            print(f"{GREEN}Indexes rebuilt successfully.{RESET}")
        except Exception as e:
            print(f"{RED}Reindex failed: {e}{RESET}", file=sys.stderr)

    report.elapsed_seconds = time.monotonic() - start_time
    print(format_report(report))


if __name__ == "__main__":
    main()
