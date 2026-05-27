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
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from claude_code_transcripts import get_project_display_name, get_session_summary

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
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
        help="Legacy flag (no longer required). Cleanup prompts now appear automatically.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed error output on failures.",
    )
    return parser.parse_args(argv)


def extract_last_timestamp(jsonl_path: Path) -> float:
    last_ts = 0.0
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ts = obj.get("timestamp", "")
                    if ts:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        last_ts = dt.timestamp()
                except (json.JSONDecodeError, ValueError):
                    continue
    except (FileNotFoundError, OSError):
        pass
    return last_ts


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


UNKNOWN_PROJECT = "_UNKNOWN"


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


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _relative_age(mtime: float) -> str:
    delta = int(time.time() - mtime)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{_plural(delta // 60, 'min')} ago"
    if delta < 86400:
        h = delta // 3600
        m = (delta % 3600) // 60
        parts = [_plural(h, "hour")]
        if m:
            parts.append(_plural(m, "min"))
        return f"{', '.join(parts)} ago"
    if delta < 604800:
        d = delta // 86400
        h = (delta % 86400) // 3600
        m = (delta % 3600) // 60
        parts = [_plural(d, "day")]
        if h:
            parts.append(_plural(h, "hour"))
        if m:
            parts.append(_plural(m, "min"))
        return f"{', '.join(parts)} ago"
    if delta < 2592000:
        w = delta // 604800
        d = (delta % 604800) // 86400
        h = (delta % 86400) // 3600
        parts = [_plural(w, "week")]
        if d:
            parts.append(_plural(d, "day"))
        if h:
            parts.append(_plural(h, "hour"))
        return f"{', '.join(parts)} ago"
    if delta < 31536000:
        mo = delta // 2592000
        d = (delta % 2592000) // 86400
        h = (delta % 86400) // 3600
        parts = [_plural(mo, "month")]
        if d:
            parts.append(_plural(d, "day"))
        if h:
            parts.append(_plural(h, "hour"))
        return f"{', '.join(parts)} ago"
    y = delta // 31536000
    mo = (delta % 31536000) // 2592000
    d = (delta % 2592000) // 86400
    parts = [_plural(y, "year")]
    if mo:
        parts.append(_plural(mo, "month"))
    if d:
        parts.append(_plural(d, "day"))
    return f"{', '.join(parts)} ago"


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
            return (
                "orphan",
                f"incoming {_human_size(orphan_size)} vs existing {_human_size(organized_size)}",
            )
        if organized_size > orphan_size:
            return (
                "organized",
                f"existing {_human_size(organized_size)} vs incoming {_human_size(orphan_size)}",
            )
        return "identical", f"both {_human_size(orphan_size)}"

    if orphan_jsonl and not organized_jsonl:
        return "orphan", "only incoming has JSONL"
    if organized_jsonl and not orphan_jsonl:
        return "organized", "only existing has JSONL"

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
        move_to_delete_folder(target_dir, archive_path, subfolder="replaced")
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
        if entry.name.startswith(".") or entry.name.startswith("_"):
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


@dataclass
class PlannedMove:
    uuid: str
    source: Path
    target_project: str
    is_new_project: bool
    duplicate_status: str  # "" | "skip" | "replace"
    duplicate_reason: str
    is_unknown: bool
    category_label: str  # "JSONL" | "HTML"
    source_mtime: float = 0.0
    size_delta: int = 0
    summary: str = ""


CATEGORY_LABELS = {
    Category.A_JSONL: "Session data (JSONL)",
    Category.B_HTML_ONLY: "HTML transcript only",
    Category.C_EMPTY: "Empty (nothing inside)",
    Category.D_OTHER: "Unrecognized files",
}


def format_category_table(categories: dict[Category, list]) -> str:
    lines = [
        f"{BOLD}What's in these folders:{RESET}",
        "",
        f"  {BOLD}{'Category':<36} {'Count':>6}{RESET}",
        f"  {'':=<43}",
    ]
    for cat in Category:
        label = CATEGORY_LABELS[cat]
        count = len(categories[cat])
        color = GREEN if count == 0 else CYAN
        lines.append(f"  {label:<36} {color}{count:>6}{RESET}")
    total = sum(len(v) for v in categories.values())
    lines.append(f"  {'':=<43}")
    lines.append(f"  {'Total':<36} {BOLD}{total:>6}{RESET}")
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
        lines.append(f"  {BOLD}Cleanup (moved to _DELETE):{RESET}")
        if report.cleaned_duplicates:
            lines.append(
                f"    Duplicates:           {GREEN}{report.cleaned_duplicates:>4}{RESET}"
            )
        if report.cleaned_empty:
            lines.append(
                f"    Empty:                {GREEN}{report.cleaned_empty:>4}{RESET}"
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


def compute_move_plan(
    categories: dict[Category, list[CategorizedFolder]],
    archive_path: Path,
    existing_projects: list[str],
) -> list[PlannedMove]:
    plan: list[PlannedMove] = []
    seen_projects = list(existing_projects)

    for folder in categories[Category.A_JSONL]:
        uuid = folder.path.name
        if not folder.cwd:
            target_name = UNKNOWN_PROJECT
            is_new = target_name not in seen_projects
            is_unknown = True
        else:
            target_name, is_new = resolve_target_project(folder.cwd, seen_projects)
            is_unknown = False

        target_dir = archive_path / target_name / uuid
        duplicate_status = ""
        duplicate_reason = ""
        size_delta = 0
        if target_dir.exists():
            winner, reason = compare_session_copies(folder.path, target_dir)
            duplicate_status = "replace" if winner == "orphan" else "skip"
            duplicate_reason = reason
            if duplicate_status == "replace":
                orphan_jsonl = _find_jsonl_in_dir(folder.path)
                organized_jsonl = _find_jsonl_in_dir(target_dir)
                if orphan_jsonl and organized_jsonl:
                    try:
                        size_delta = (
                            orphan_jsonl.stat().st_size - organized_jsonl.stat().st_size
                        )
                    except OSError:
                        pass

        source_mtime = 0.0
        if folder.jsonl_path and folder.jsonl_path.exists():
            source_mtime = extract_last_timestamp(folder.jsonl_path)
            if not source_mtime:
                try:
                    source_mtime = folder.jsonl_path.stat().st_mtime
                except OSError:
                    pass

        summary = ""
        if folder.jsonl_path and folder.jsonl_path.exists():
            try:
                raw = get_session_summary(folder.jsonl_path, max_length=80)
                if raw and raw != "(no summary)":
                    cleaned = " ".join(raw.split())
                    summary = cleaned[:60] + "..." if len(cleaned) > 60 else cleaned
            except Exception:
                pass

        if is_new and target_name not in seen_projects:
            seen_projects.append(target_name)

        plan.append(
            PlannedMove(
                uuid=uuid,
                source=folder.path,
                target_project=target_name,
                is_new_project=is_new,
                duplicate_status=duplicate_status,
                duplicate_reason=duplicate_reason,
                is_unknown=is_unknown,
                category_label="JSONL",
                source_mtime=source_mtime,
                size_delta=size_delta,
                summary=summary,
            )
        )

    for folder in categories[Category.B_HTML_ONLY]:
        uuid = folder.path.name
        project_name = None
        for html_file in folder.html_files:
            project_name = extract_project_from_html(html_file)
            if project_name:
                break

        if not project_name:
            target_name = UNKNOWN_PROJECT
            is_new = target_name not in seen_projects
            is_unknown = True
        else:
            match = find_matching_project(project_name, seen_projects)
            is_new = match is None
            target_name = match or project_name
            is_unknown = False

        target_dir = archive_path / target_name / uuid
        duplicate_status = ""
        duplicate_reason = ""
        size_delta = 0
        if target_dir.exists():
            winner, reason = compare_session_copies(folder.path, target_dir)
            duplicate_status = "replace" if winner == "orphan" else "skip"
            duplicate_reason = reason
            if duplicate_status == "replace":
                orphan_jsonl = _find_jsonl_in_dir(folder.path)
                organized_jsonl = _find_jsonl_in_dir(target_dir)
                if orphan_jsonl and organized_jsonl:
                    try:
                        size_delta = (
                            orphan_jsonl.stat().st_size - organized_jsonl.stat().st_size
                        )
                    except OSError:
                        pass

        source_mtime = 0.0
        html_for_mtime = folder.html_files[0] if folder.html_files else None
        if html_for_mtime and html_for_mtime.exists():
            try:
                source_mtime = html_for_mtime.stat().st_mtime
            except OSError:
                pass

        if is_new and target_name not in seen_projects:
            seen_projects.append(target_name)

        plan.append(
            PlannedMove(
                uuid=uuid,
                source=folder.path,
                target_project=target_name,
                is_new_project=is_new,
                duplicate_status=duplicate_status,
                duplicate_reason=duplicate_reason,
                is_unknown=is_unknown,
                category_label="HTML",
                source_mtime=source_mtime,
                size_delta=size_delta,
            )
        )

    return plan


def format_move_plan(plan: list[PlannedMove]) -> str:
    if not plan:
        return ""

    replaces = sorted(
        [p for p in plan if p.duplicate_status == "replace"],
        key=lambda p: p.source_mtime,
        reverse=True,
    )
    moves = sorted(
        [p for p in plan if p.duplicate_status == "" and not p.is_unknown],
        key=lambda p: p.source_mtime,
        reverse=True,
    )
    unknowns = sorted(
        [p for p in plan if p.is_unknown and p.duplicate_status != "skip"],
        key=lambda p: p.source_mtime,
        reverse=True,
    )
    skips = sorted(
        [p for p in plan if p.duplicate_status == "skip"],
        key=lambda p: p.source_mtime,
        reverse=True,
    )

    MAX_ENTRIES = 15

    lines = [f"{BOLD}Move plan:{RESET}", ""]

    def _format_entry(
        p: PlannedMove, show_delta: bool = False, show_new_tag: bool = False
    ) -> None:
        delta_str = ""
        if show_delta and p.size_delta > 0:
            delta_str = f"  ({GREEN}+{_human_size(p.size_delta)}{RESET})"
        elif show_delta and p.size_delta < 0:
            delta_str = f"  ({YELLOW}-{_human_size(abs(p.size_delta))}{RESET})"
        age_str = ""
        if p.source_mtime:
            age_str = f"  {DIM}({_relative_age(p.source_mtime)}){RESET}"
        new_tag = ""
        if show_new_tag and p.is_new_project:
            new_tag = f"  {MAGENTA}(new project){RESET}"
        lines.append(
            f"  {DIM}{p.uuid}{RESET} → {BOLD}{p.target_project}{RESET}{delta_str}{age_str}{new_tag}"
        )

    def _format_group(
        entries: list[PlannedMove],
        show_delta: bool = False,
        show_new_tag: bool = False,
        compact: bool = False,
    ) -> None:
        shown = entries[:MAX_ENTRIES]
        remaining = len(entries) - len(shown)
        for p in shown:
            if compact:
                age_str = ""
                if p.source_mtime:
                    age_str = f"  {DIM}({_relative_age(p.source_mtime)}){RESET}"
                lines.append(
                    f"  {DIM}{p.uuid}{RESET} → {BOLD}{p.target_project}{RESET}{age_str}"
                )
            else:
                _format_entry(p, show_delta=show_delta, show_new_tag=show_new_tag)
        if remaining > 0:
            lines.append(f"  {DIM}... and {CYAN}{remaining}{RESET}{DIM} more{RESET}")
        lines.append("")

    if replaces:
        lines.append(
            f"{BOLD}{YELLOW}Replace {CYAN}{len(replaces)}{RESET}{BOLD}{YELLOW} session{'s' if len(replaces) != 1 else ''}?{RESET} {DIM}(old copies backed up to _DELETE){RESET}"
        )
        _format_group(replaces, show_delta=True)

    if moves:
        lines.append(
            f"{BOLD}{BLUE}Move {CYAN}{len(moves)}{RESET}{BOLD}{BLUE} session{'s' if len(moves) != 1 else ''}?{RESET}"
        )
        _format_group(moves, show_new_tag=True)

    if unknowns:
        lines.append(
            f"{BOLD}{YELLOW}Move {CYAN}{len(unknowns)}{RESET}{BOLD}{YELLOW} session{'s' if len(unknowns) != 1 else ''} to _UNKNOWN?{RESET}"
        )
        _format_group(unknowns)

    if skips:
        lines.append(
            f"{BOLD}{CYAN}Move {len(skips)} duplicate{'s' if len(skips) != 1 else ''} to _DELETE?{RESET}"
        )
        _format_group(skips, compact=True)

    def _group_size(entries: list[PlannedMove]) -> int:
        total = 0
        for p in entries:
            jsonl = _find_jsonl_in_dir(p.source) if p.source.exists() else None
            if jsonl and jsonl.exists():
                try:
                    total += jsonl.stat().st_size
                except OSError:
                    pass
        return total

    if replaces or moves or unknowns or skips:
        lines.append(f"{BOLD}Summary:{RESET}")
        if replaces:
            size = _group_size(replaces)
            lines.append(
                f"  Add as replacement:  {CYAN}{_plural(len(replaces), 'session')}{RESET}  ({GREEN}+{_human_size(size)}{RESET})"
            )
        if moves:
            size = _group_size(moves)
            lines.append(
                f"  Add new:             {CYAN}{_plural(len(moves), 'session')}{RESET}  ({BLUE}{_human_size(size)}{RESET})"
            )
        if unknowns:
            size = _group_size(unknowns)
            lines.append(
                f"  To _UNKNOWN:         {CYAN}{_plural(len(unknowns), 'session')}{RESET}  ({YELLOW}{_human_size(size)}{RESET})"
            )
        if skips:
            size = _group_size(skips)
            lines.append(
                f"  To _DELETE:          {CYAN}{_plural(len(skips), 'duplicate')}{RESET}  ({RED}{_human_size(size)}{RESET})"
            )
        lines.append("")

    return "\n".join(lines)


@dataclass
class IndexChange:
    path: Path
    name: str
    old_size: int
    new_size: int

    @property
    def delta(self) -> int:
        return self.new_size - self.old_size

    @property
    def changed(self) -> bool:
        return self.old_size != self.new_size


def reindex_archive(archive_path: Path) -> list[IndexChange]:
    from claude_code_transcripts import _generate_master_index, _generate_project_index

    changes: list[IndexChange] = []
    projects = scan_archive_for_projects(archive_path)

    for project in projects:
        project_dir = archive_path / project["name"]
        index_path = project_dir / "index.html"
        old_size = index_path.stat().st_size if index_path.exists() else 0
        _generate_project_index(project, project_dir)
        new_size = index_path.stat().st_size if index_path.exists() else 0
        changes.append(IndexChange(index_path, project["name"], old_size, new_size))

    master_path = archive_path / "index.html"
    old_size = master_path.stat().st_size if master_path.exists() else 0
    _generate_master_index(projects, archive_path)
    new_size = master_path.stat().st_size if master_path.exists() else 0
    changes.append(IndexChange(master_path, "index.html (master)", old_size, new_size))

    return changes


def move_to_delete_folder(
    source: Path, archive_path: Path, subfolder: str = "duplicates"
) -> Path:
    delete_dir = archive_path / "_DELETE" / subfolder
    delete_dir.mkdir(parents=True, exist_ok=True)
    target = delete_dir / source.name
    if not target.exists():
        shutil.move(str(source), str(target))
        return target
    counter = 1
    while True:
        candidate = delete_dir / f"{source.name}-{counter}"
        if not candidate.exists():
            shutil.move(str(source), str(candidate))
            return candidate
        counter += 1


def format_delete_plan(
    duplicate_paths: list[Path],
    empty_paths: list[Path],
    duplicate_reasons: dict[str, str] | None = None,
) -> str:
    if not duplicate_paths and not empty_paths:
        return ""

    if duplicate_reasons is None:
        duplicate_reasons = {}

    lines = []

    if duplicate_paths:
        lines.append(
            f"{BOLD}[{RED}MOVE TO _DELETE: DUPLICATES{RESET}{BOLD}]{RESET} ({CYAN}{len(duplicate_paths)}{RESET})"
        )
        sorted_dups = sorted(duplicate_paths, key=lambda p: p.name)
        for p in sorted_dups[:15]:
            reason = duplicate_reasons.get(p.name, "")
            reason_str = f"  ({reason})" if reason else ""
            age_str = ""
            jsonl = _find_jsonl_in_dir(p) if p.exists() else None
            if jsonl and jsonl.exists():
                ts = extract_last_timestamp(jsonl)
                if not ts:
                    try:
                        ts = jsonl.stat().st_mtime
                    except OSError:
                        ts = 0.0
                if ts:
                    age_str = f"  {DIM}({_relative_age(ts)}){RESET}"
            lines.append(f"  {DIM}{p.name}{RESET}{reason_str}{age_str}")
        if len(sorted_dups) > 15:
            lines.append(
                f"  {DIM}... and {CYAN}{len(sorted_dups) - 15}{RESET}{DIM} more{RESET}"
            )
        lines.append("")

    if empty_paths:
        lines.append(
            f"{BOLD}[{RED}MOVE TO _DELETE: EMPTY{RESET}{BOLD}]{RESET} ({CYAN}{len(empty_paths)}{RESET})"
        )
        sorted_empty = sorted(empty_paths, key=lambda p: p.name)
        for p in sorted_empty[:15]:
            lines.append(f"  {DIM}{p.name}{RESET}")
        if len(sorted_empty) > 15:
            lines.append(f"  ... and {CYAN}{len(sorted_empty) - 15}{RESET} more")
        lines.append("")

    return "\n".join(lines)


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
    print(f"Projects: {CYAN}{len(projects)}{RESET}")
    print(f"Sessions: {CYAN}{total_sessions:,}{RESET}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    archive_path = Path(args.path).resolve()

    if not archive_path.is_dir():
        print(f"{RED}Error: {archive_path} is not a directory{RESET}", file=sys.stderr)
        sys.exit(1)

    print()
    if args.dry_run:
        print(f"{YELLOW}{BOLD}DRY RUN - no changes will be made{RESET}\n")
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
            f"\n{BOLD}Found {CYAN}{len(uuid_folders)}{RESET}{BOLD} orphan UUID folders:{RESET}"
        )
        for folder in uuid_folders[:15]:
            print(f"    {DIM}{folder.name}{RESET}")
        if len(uuid_folders) > 15:
            print(
                f"    {DIM}... and {CYAN}{len(uuid_folders) - 15}{RESET}{DIM} more{RESET}"
            )
        print()

        categories = categorize_all(uuid_folders)
        print(format_category_table(categories))
        print()

        existing = list_existing_projects(archive_path)
        plan = compute_move_plan(categories, archive_path, existing)

        # Collect Category C + D info
        empties = categories[Category.C_EMPTY]
        others = categories[Category.D_OTHER]
        for folder in empties:
            report.skipped_empty += 1
            report.empty_paths.append(folder.path)
        for folder in others:
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

        # Display move plan
        plan_output = format_move_plan(plan)
        if plan_output:
            print(plan_output)

        # Display additional groups (empty, unrecognized)
        if empties:
            print(
                f"{BOLD}{RED}Move {CYAN}{len(empties)}{RESET}{BOLD}{RED} empty folder{'s' if len(empties) != 1 else ''} to _DELETE?{RESET}"
            )
            for folder in empties[:15]:
                print(f"  {DIM}{folder.path.name}{RESET}")
            if len(empties) > 15:
                print(
                    f"  {DIM}... and {CYAN}{len(empties) - 15}{RESET}{DIM} more{RESET}"
                )
            print()

        if others:
            print(
                f"{BOLD}{RED}Move {CYAN}{len(others)}{RESET}{BOLD}{RED} unrecognized folder{'s' if len(others) != 1 else ''} to _DELETE?{RESET}"
            )
            for folder in others[:15]:
                print(f"  {DIM}{folder.path.name}{RESET}")
            if len(others) > 15:
                print(
                    f"  {DIM}... and {CYAN}{len(others) - 15}{RESET}{DIM} more{RESET}"
                )
            print()

        # Build lookup: uuid -> (CategorizedFolder, is_jsonl)
        folder_lookup: dict[str, tuple[CategorizedFolder, bool]] = {}
        for folder in categories[Category.A_JSONL]:
            folder_lookup[folder.path.name] = (folder, True)
        for folder in categories[Category.B_HTML_ONLY]:
            folder_lookup[folder.path.name] = (folder, False)

        # Split plan into action groups
        replaces = [p for p in plan if p.duplicate_status == "replace"]
        moves = [p for p in plan if p.duplicate_status == "" and not p.is_unknown]
        unknowns = [p for p in plan if p.is_unknown and p.duplicate_status != "skip"]
        skips = [p for p in plan if p.duplicate_status == "skip"]

        def _process_group(entries: list[PlannedMove]) -> None:
            for entry in entries:
                cat_folder, is_jsonl = folder_lookup[entry.uuid]
                if is_jsonl:
                    result = process_category_a(
                        cat_folder,
                        archive_path,
                        existing,
                        args.dry_run,
                        verbose=args.verbose,
                    )
                else:
                    result = process_category_b(
                        cat_folder,
                        archive_path,
                        existing,
                        args.dry_run,
                        verbose=args.verbose,
                    )
                _tally_result(result, report, is_jsonl_category=is_jsonl)

        def _move_to_delete(
            paths: list[Path], label: str, subfolder: str = "duplicates"
        ) -> None:
            if args.dry_run:
                print(
                    f"  {YELLOW}Dry run: would move {len(paths)} {label} to _DELETE/{subfolder}{RESET}"
                )
                return
            for p in paths:
                try:
                    if p.exists():
                        move_to_delete_folder(p, archive_path, subfolder=subfolder)
                        if p in report.duplicate_paths:
                            report.cleaned_duplicates += 1
                        else:
                            report.cleaned_empty += 1
                except OSError as e:
                    report.outliers.append((p.name, f"Cleanup failed: {e}"))

        # Prompt for each group (heading in the plan doubles as the question)
        if replaces:
            if confirm(
                f"Proceed with replacing {len(replaces)} session{'s' if len(replaces) != 1 else ''}?",
                args.yes,
            ):
                _process_group(replaces)
            else:
                print(f"  {YELLOW}Skipped.{RESET}")
            print()

        if moves:
            if confirm(
                f"Proceed with moving {len(moves)} session{'s' if len(moves) != 1 else ''}?",
                args.yes,
            ):
                _process_group(moves)
            else:
                print(f"  {YELLOW}Skipped.{RESET}")
            print()

        if unknowns:
            if confirm(
                f"Proceed with moving {len(unknowns)} session{'s' if len(unknowns) != 1 else ''} to _UNKNOWN?",
                args.yes,
            ):
                _process_group(unknowns)
            else:
                print(f"  {YELLOW}Skipped.{RESET}")
            print()

        if skips:
            for entry in skips:
                cat_folder, is_jsonl = folder_lookup[entry.uuid]
                result = MoveResult(
                    uuid=entry.uuid,
                    source=entry.source,
                    target_project=entry.target_project,
                    success=True,
                    is_duplicate=True,
                )
                _tally_result(result, report, is_jsonl_category=is_jsonl)

            if confirm(
                f"Proceed with moving {len(skips)} duplicate{'s' if len(skips) != 1 else ''} to _DELETE?",
                args.yes,
            ):
                _move_to_delete(
                    report.duplicate_paths, "duplicate orphans", subfolder="duplicates"
                )
            else:
                print(f"  {YELLOW}Skipped.{RESET}")
            print()

        if empties:
            if confirm(
                f"Proceed with moving {len(empties)} empty folder{'s' if len(empties) != 1 else ''} to _DELETE?",
                args.yes,
            ):
                _move_to_delete(report.empty_paths, "empty folders", subfolder="empty")
            else:
                print(f"  {YELLOW}Skipped.{RESET}")
            print()

        if others:
            if confirm(
                f"Proceed with moving {len(others)} unrecognized folder{'s' if len(others) != 1 else ''} to _DELETE?",
                args.yes,
            ):
                other_paths = [f.path for f in others]
                _move_to_delete(
                    other_paths, "unrecognized folders", subfolder="unrecognized"
                )
            else:
                print(f"  {YELLOW}Skipped.{RESET}")
            print()

    # Reindex (skip for dry-run and --no-reindex)
    if not args.no_reindex and not args.dry_run:
        print(f"\n{BOLD}Rebuilding indexes...{RESET}")
        try:
            changes = reindex_archive(archive_path)
            report.reindexed = True

            def _delta_str(c: IndexChange) -> str:
                if c.old_size == 0:
                    return f"{GREEN}new ({_human_size(c.new_size)}){RESET}"
                if c.delta > 0:
                    return f"{GREEN}+{_human_size(c.delta)}{RESET}"
                if c.delta < 0:
                    return f"{YELLOW}-{_human_size(abs(c.delta))}{RESET}"
                return f"{DIM}no change{RESET}"

            master = [c for c in changes if "master" in c.name]
            projects_changed = [
                c for c in changes if "master" not in c.name and c.changed
            ]

            if projects_changed or (master and master[0].changed):
                print(f"{GREEN}Indexes rebuilt.{RESET}")
                print()
                if projects_changed:
                    print(
                        f"  {BOLD}Project indexes updated ({CYAN}{len(projects_changed)}{RESET}{BOLD}):{RESET}"
                    )
                    for c in projects_changed:
                        print(f"    {DIM}{c.name}/index.html{RESET}  ({_delta_str(c)})")
                    print()
                if master:
                    print(
                        f"  {BOLD}Master index:{RESET}  {DIM}index.html{RESET}  ({_delta_str(master[0])})"
                    )
            else:
                print(f"{GREEN}Indexes rebuilt. No changes.{RESET}")
        except Exception as e:
            print(f"{RED}Reindex failed: {e}{RESET}", file=sys.stderr)
    elif args.dry_run and not args.no_reindex:
        print(f"\n  Reindex: {YELLOW}skipped (dry run){RESET}")

    report.elapsed_seconds = time.monotonic() - start_time
    print(format_report(report))


if __name__ == "__main__":
    main()
