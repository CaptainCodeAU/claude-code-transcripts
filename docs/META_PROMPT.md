# Meta Prompt: claude-code-transcripts Project Context

Paste this into a new Claude Code session to get full working context for this project without needing prior conversation history.

---

## Project Overview

**claude-code-transcripts** is a Python CLI tool that converts Claude Code session files (JSON/JSONL) into browseable, paginated HTML transcripts. It's a fork of [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts) by Simon Willison, maintained at `CaptainCodeAU/claude-code-transcripts`.

### Stack
- Python 3.10+, managed with `uv`
- Click CLI framework, Jinja2 templates, Markdown rendering
- Tests: pytest (run with `uv run pytest`)
- Formatter: Black (run with `uv run black .`)
- No CI pipeline, tests run locally

### Repository Structure
```
src/claude_code_transcripts/
  __init__.py          Main package: CLI commands, session parsing, HTML generation
  templates/           Jinja2 HTML templates for transcript rendering

scripts/
  reconcile_sessions.py   Standalone script (imports from the package)

tests/
  test_all.py             Tests for the main CLI/package
  test_generate_html.py   Tests for HTML generation
  test_reconcile.py       Tests for reconcile_sessions.py

docs/
  CLI.md                  Flag-by-flag CLI reference
  REGENERATE.md           Recipes for re-running the generator
  RECONCILE_FLOW.md       ASCII flowcharts for reconcile decision logic
```

### CLI Commands
1. `local` (default) - interactive picker for local sessions from `~/.claude/projects`
2. `json` - convert a specific JSON/JSONL file
3. `web` - fetch and convert sessions from the Claude API
4. `all` - batch convert all local sessions to a browseable archive
5. `scripts/reconcile_sessions.py` - organize orphan session folders (standalone script)

### Fork Enhancements (beyond upstream)
- Dark mode with floating toggle
- Copy-to-clipboard buttons on all blocks
- Wider responsive layout (1400px)
- Markdown rendering in messages
- `--json/--no-json` flag for source file archival
- Reconciliation script with full UX

---

## The Reconcile Script (scripts/reconcile_sessions.py)

This is the most actively developed part of the project. It organizes orphan UUID-named session folders sitting at the archive root into their correct project subdirectories.

### How It Works
1. Scans the archive for UUID-named orphan folders
2. Categorizes each: has JSONL, HTML only, empty, or unrecognized
3. Derives the target project from the JSONL `cwd` field (or HTML content as fallback)
4. Compares duplicates by JSONL file size (larger = more complete, since JSONL is append-only)
5. Shows a move plan with action-verb headings that double as prompts
6. Each group has its own confirmation; declining skips and continues
7. Rebuilds indexes only if the archive actually changed

### Key Flags
- `--dry-run` - show plan, touch nothing (also skips reindex)
- `--yes` - auto-confirm all prompts
- `--no-reindex` - skip index rebuilding
- `--fix-mtimes` - bulk-correct file and project folder mtimes to match JSONL session timestamps
- `--verbose` - show error details
- `--cleanup` - legacy flag (no longer needed, prompts appear automatically)

### Move Plan Groups (in order)
| Heading | Condition | Destination |
|---------|-----------|-------------|
| Replace N sessions? | Orphan JSONL larger than organized copy | Project dir (old copy to `_DELETE/replaced/`) |
| Move N sessions? | Target dir doesn't exist | Project dir |
| Move N to _UNKNOWN? | No cwd extractable | `_UNKNOWN/` |
| Move N duplicates to _DELETE? | Organized copy same size or larger | `_DELETE/duplicates/` |
| Move N empty folders to _DELETE? | Folder contains no files | `_DELETE/empty/` |
| Move N unrecognized to _DELETE? | Files but no .jsonl/.html | `_DELETE/unrecognized/` |

### Special Folders (underscore-prefixed, excluded from project listings)
- `_DELETE/` with subfolders: `duplicates/`, `empty/`, `unrecognized/`, `replaced/`
- `_UNKNOWN/` for sessions that can't be matched to a project

### Session Timestamps
- Ages are derived from the last `timestamp` field INSIDE the JSONL (ISO 8601 UTC with `Z` suffix), NOT from file mtime
- File mtime reflects when the file was copied, not when the session happened
- Falls back to file mtime only for non-standard JSONL formats without `timestamp` fields
- `--fix-mtimes` corrects file, session folder, and project folder mtimes across the archive to match JSONL timestamps
- Mtimes auto-corrected after each session move during reconciliation
- Project folder mtimes set to their newest session's JSONL timestamp (after moves and via `--fix-mtimes`)

### Output Styling
- Dim UUIDs, bold project names, dim ages in parentheses
- Colored headings: yellow=replace, blue=move, red=empty/unrecognized, cyan=duplicates
- Compact age format: `1 M, 3 d, 18 h, 34 m ago` (up to 4 levels)
- Lists truncated at 15 entries with "... and N more"
- DRY RUN banner at the very top of output
- Reindex output shows project + master index separately with size deltas
- Move/Replace groups show a "Destinations:" block listing unique target projects with session counts
- Report hides zero-count lines (only non-zero breakdown rows shown)
- Summary section shows per-destination totals with color-coded sizes

### JSONL Format
Standard Claude Code JSONL lines have: `type`, `timestamp`, `cwd`, `sessionId`, `message`, etc.
Non-standard formats (e.g., older exports) may have only `role` + `message` with no `cwd` or `timestamp`.
Archive copies are byte-for-byte identical to source files in `~/.claude/projects/`.

---

## Development Conventions

### TDD Required
Always write a failing test first, watch it fail, then make it pass. Tests for the reconcile script are in `tests/test_reconcile.py`. The test file adds `scripts/` to `sys.path` for imports.

### Commit Style
- Descriptive single-line summaries, body for details
- Bundle test + implementation + docs together
- Format with `uv run black .` before committing
- Commit early and often

### Test Patterns
- All `main()` integration tests use `--yes` to skip interactive prompts
- `_make_uuid_folder(tmp_path, uuid, cwd=...)` helper creates test session folders
- `@patch("reconcile_sessions.subprocess")` mocks HTML regeneration in tests that call `process_category_a`
- ANSI color codes in output break substring assertions; assert on words that don't span color boundaries

### Documentation
Four docs to keep in sync when changing the reconcile script:
1. `README.md` (reconcile section, lines ~227-252)
2. `docs/CLI.md` (reconcile section, lines ~229-278)
3. `docs/REGENERATE.md` (rebuilding indexes section)
4. `docs/RECONCILE_FLOW.md` (ASCII flowcharts, all 7 diagrams)

---

## Archive Layout

```
~/CODE/my-claude-code-transcripts/
  index.html                           Master index (lists all projects)
  MyOrg-MyProject/
    index.html                         Project index (lists sessions)
    fdcff093-.../
      fdcff093-....jsonl               Session data (identical to source)
      index.html                       Session transcript index
      page-001.html                    Paginated transcript pages
  _DELETE/
    duplicates/                        Orphan copies where organized version kept
    empty/                             Empty orphan folders
    unrecognized/                      Non-session files
    replaced/                          Old copies overwritten by REPLACE
  _UNKNOWN/                            Sessions with no extractable project
  _legacy_*/                           Old project folders (skipped by scanner)
```

---

## Durability Warnings

1. **Never use `shutil.rmtree()` for cleanup.** All deletions use `move_to_delete_folder()` which soft-deletes to `_DELETE/<subfolder>/`. The old `--cleanup` flag used rmtree; it's now legacy.

2. **REPLACE backs up the old copy.** `_handle_duplicate()` calls `move_to_delete_folder(target_dir, archive_path, subfolder="replaced")` before moving the orphan in. Never change this to permanent deletion.

3. **File mtime is not session time.** Always use `extract_last_timestamp(jsonl_path)` for session ages and sorting, not `stat().st_mtime`. Mtime reflects copy date.

4. **`scan_archive_for_projects()` skips `_`-prefixed dirs.** This is intentional. `_DELETE`, `_UNKNOWN`, and `_legacy_*` folders must not appear in project listings or index generation.

5. **Reindex only runs when the archive changed.** The `archive_changed` flag checks `report.moved_jsonl + moved_html + moved_unknown + replaced + cleaned_duplicates + cleaned_empty > 0`. Don't bypass this check.

6. **Group headings ARE the prompts.** The move plan headings ("Replace N sessions?") double as the action description. The `confirm()` call uses "Proceed with..." phrasing. Don't separate plan display from prompts.

7. **Tests use `--yes` for auto-confirmation.** When piping stdin (non-TTY), `confirm()` auto-returns True. All integration tests rely on this. Don't change `confirm()` behavior for non-TTY.

---

## Quick Start Commands

```bash
# Run tests
uv run pytest

# Run development version
uv run claude-code-transcripts --help

# Run reconcile script (dry-run)
uv run python scripts/reconcile_sessions.py --dry-run ~/CODE/my-claude-code-transcripts/

# Run reconcile script (for real)
uv run python scripts/reconcile_sessions.py --yes ~/CODE/my-claude-code-transcripts/

# Bulk-correct file mtimes
uv run python scripts/reconcile_sessions.py --fix-mtimes --yes ~/CODE/my-claude-code-transcripts/

# Format code
uv run black .
```
