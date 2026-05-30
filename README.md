# claude-code-transcripts

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/CaptainCodeAU/claude-code-transcripts/blob/master/LICENSE)

> **Fork of [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)** by [Simon Willison](https://simonwillison.net/). Original project background: [A new way to extract detailed transcripts from Claude Code](https://simonwillison.net/2025/Dec/25/claude-code-transcripts/). This fork adds enhanced rendering, archival features, and UX improvements while staying compatible with upstream session formats.

Convert Claude Code session files (JSON or JSONL) to clean, mobile-friendly HTML pages with pagination.

[Example transcript](https://static.simonwillison.net/static/2025/claude-code-microjs/index.html) produced using the upstream tool.

## Fork enhancements

Features added in this fork beyond the upstream project.

**Rendering and UX:**
- **Dark mode by default** with a floating light/dark toggle on every page
- **Copy-to-clipboard buttons** on all blocks (code, tool inputs/outputs, text, diffs, commit cards, thinking, and full messages)
- **Wider responsive layout** (1400px max-width with breakpoints at 1024px and 600px)
- **Markdown rendering** in assistant and user messages (list preprocessing, GFM strikethrough/task lists, CSS for headings/tables/blockquotes/lists)
- **`--json/--no-json` flag** across all subcommands (default: on) to include/suppress source file archival
- **`<task-notification>` fix** preventing background task completions from rendering as user messages
- **Batch archive source inclusion** via the `all` command with `--json/--no-json` support

**Architecture and automation (0.7):**
- **Layered package** with a stdlib-only core: importing `claude_code_transcripts.core.*` pulls zero third-party deps (locked by a fence test), so a future stdlib-only plugin shim can share naming and resolution logic without dragging in jinja2 / markdown / httpx. The CLI itself is stdlib `argparse` plus a stdlib arrow-key session picker, so it no longer depends on `click` / `click-default-group` / `questionary`
- **SessionEnd capture pipeline** via the new [`hook`](docs/CLI.md#hook) and [`render`](docs/CLI.md#render) subcommands: cwd-first project-name resolution, idempotent skip on unchanged sessions, fast capture, and a detached background render so session shutdown is never blocked
- **Env-driven configuration** for the pipeline: `TRANSCRIPT_EXPORT_DIR`, opt-in `TRANSCRIPT_VOICE_URL` / `TRANSCRIPT_VOICE_ID`, `TRANSCRIPT_OPEN_FOLDER`, `SKIP_SESSION_END_HOOK` (see [`docs/CLI.md#environment-variables`](docs/CLI.md#environment-variables))
- **Companion plugin** for automatic session-end export via [claude-transcript-exporter](https://github.com/CaptainCodeAU/gz-claude-code-plugins): now a thin wrapper that pipes the SessionEnd payload to `claude-code-transcripts hook` with no business logic of its own, so naming/resolve/skip/render stay in one place and can't drift
- **Reconciliation script** (`scripts/reconcile_sessions.py`) with two modes: orphan handling (folds UUID folders into projects) and `--merge-drift` (re-derives the correct project from each session's JSONL `cwd`, merges drifted project folders, soft-deletes byte-equal duplicates to `_DELETE/`)

## Installation

> **PyPI hosts the upstream version, not this fork.** `uv tool install claude-code-transcripts` (without a URL) pulls the original simonw release from PyPI, without any of the fork enhancements listed above (the 0.7 capture pipeline, drift remediation, layered architecture, etc.). Install from the git URL below instead.

Install the latest tagged release of this fork:

```bash
uv tool install "git+https://github.com/CaptainCodeAU/claude-code-transcripts.git@0.7"
```

Or track HEAD on `master`:

```bash
uv tool install "git+https://github.com/CaptainCodeAU/claude-code-transcripts.git"
```

Upgrade a previously git-installed copy (re-fetches the same ref you installed from):

```bash
uv tool upgrade claude-code-transcripts
```

To move between tagged releases (e.g., from `0.7` to a later `0.8`), reinstall with the new ref:

```bash
uv tool install --reinstall "git+https://github.com/CaptainCodeAU/claude-code-transcripts.git@0.8"
```

Or run it without installing:

```bash
uvx --from "git+https://github.com/CaptainCodeAU/claude-code-transcripts.git@0.7" claude-code-transcripts --help
```

## Usage

This tool converts Claude Code session files into browseable multi-page HTML transcripts.

Six subcommands plus a standalone reconciliation script. The first four are interactive; `hook` and `render` are the automated SessionEnd capture pipeline, normally invoked by the companion plugin rather than by you directly.

- `local` (default) - select from local Claude Code sessions stored in `~/.claude/projects`
- `web` - select from web sessions via the Claude API
- `json` - convert a specific JSON or JSONL session file
- `all` - convert all local sessions to a browsable HTML archive
- `hook` - capture a session at SessionEnd, reading the JSON payload from stdin
- `render` - render an already-filed session's HTML (the background child `hook` spawns; also usable standalone)
- `scripts/reconcile_sessions.py` - organize orphan and drifted session folders

The quickest way to view a recent local session:

```bash
claude-code-transcripts
```

This shows an interactive picker to select a session, generates HTML, and opens it in your default browser.

### Output options

All commands support these options:

- `-o, --output DIRECTORY` - output directory (default: writes to temp dir and opens browser)
- `-a, --output-auto` - auto-name output subdirectory based on session ID or filename
- `--repo OWNER/NAME` - GitHub repo for commit links (auto-detected if not specified). For `web` command, also filters the session list.
- `--open` - open the generated `index.html` in your default browser (default if no `-o` specified)
- `--gist` - upload the generated HTML files to a GitHub Gist and output a preview URL
- `--json` / `--no-json` - include the original session file in the output directory (default: include; use `--no-json` to suppress)

The generated output includes:
- `index.html` - an index page with a timeline of prompts and commits
- `page-001.html`, `page-002.html`, etc. - paginated transcript pages

### Local sessions

Local Claude Code sessions are stored as JSONL files in `~/.claude/projects`. Run with no arguments to select from recent sessions:

```bash
claude-code-transcripts
# or explicitly:
claude-code-transcripts local
```

Use `--limit` to control how many sessions are shown (default: 10):

```bash
claude-code-transcripts local --limit 20
```

### Web sessions

Import sessions directly from the Claude API:

```bash
# Interactive session picker
claude-code-transcripts web

# Import a specific session by ID
claude-code-transcripts web SESSION_ID

# Import and publish to gist
claude-code-transcripts web SESSION_ID --gist
```

The session picker displays sessions grouped by their associated GitHub repository:

```
simonw/datasette              2025-01-15T10:30:00  Fix the bug in query parser
simonw/llm                    2025-01-14T09:00:00  Add streaming support
(no repo)                     2025-01-13T14:22:00  General coding session
```

Use `--repo` to filter the session list to a specific repository:

```bash
claude-code-transcripts web --repo simonw/datasette
```

On macOS, API credentials are automatically retrieved from your keychain (requires being logged into Claude Code). On other platforms, provide `--token` and `--org-uuid` manually.

### Publishing to GitHub Gist

Use the `--gist` option to automatically upload your transcript to a GitHub Gist and get a shareable preview URL:

```bash
claude-code-transcripts --gist
claude-code-transcripts web --gist
claude-code-transcripts json session.json --gist
```

This will output something like:
```
Gist: https://gist.github.com/username/abc123def456
Preview: https://gisthost.github.io/?abc123def456/index.html
Files: /var/folders/.../session-id
```

The preview URL uses [gisthost.github.io](https://gisthost.github.io/) to render your HTML gist. The tool automatically injects JavaScript to fix relative links when served through gisthost.

Combine with `-o` to keep a local copy:

```bash
claude-code-transcripts json session.json -o ./my-transcript --gist
```

**Requirements:** The `--gist` option requires the [GitHub CLI](https://cli.github.com/) (`gh`) to be installed and authenticated (`gh auth login`).

### Auto-naming output directories

Use `-a/--output-auto` to automatically create a subdirectory named after the session:

```bash
# Creates ./session_ABC123/ subdirectory
claude-code-transcripts web SESSION_ABC123 -a

# Creates ./transcripts/session_ABC123/ subdirectory
claude-code-transcripts web SESSION_ABC123 -o ./transcripts -a
```

### Including the source file

The original session file is included in the output directory by default:

```bash
claude-code-transcripts json session.json -o ./my-transcript
```

This will output:
```
JSON: ./my-transcript/session_ABC.json (245.3 KB)
```

This is useful for archiving the source data alongside the HTML output. To suppress the source-file copy, pass `--no-json`:

```bash
claude-code-transcripts json session.json -o ./my-transcript --no-json
```

### Converting from JSON/JSONL files

Convert a specific session file directly:

```bash
claude-code-transcripts json session.json -o output-directory/
claude-code-transcripts json session.jsonl --open
```
This works with both JSONL files in the `~/.claude/projects/` folder and JSON session files extracted from Claude Code for web.

The `json` command can take a URL to a JSON or JSONL file as an alternative to a path on disk.

### Converting all sessions

Convert all your local Claude Code sessions to a browsable HTML archive:

```bash
claude-code-transcripts all
```

This creates a directory structure with:
- A master index listing all projects
- Per-project pages listing sessions
- Individual session transcripts

Options:

- `-s, --source DIRECTORY` - source directory (default: `~/.claude/projects`)
- `-o, --output DIRECTORY` - output directory (default: `./claude-archive`)
- `--include-agents` - include agent session files (excluded by default)
- `--dry-run` - show what would be converted without creating files
- `--open` - open the generated archive in your default browser
- `-q, --quiet` - suppress all output except errors
- `--json` / `--no-json` - copy each session's source `.jsonl` into its output directory alongside the rendered HTML (default: on; use `--no-json` to suppress)

Examples:

```bash
# Preview what would be converted
claude-code-transcripts all --dry-run

# Convert all sessions and open in browser
claude-code-transcripts all --open

# Convert to a specific directory
claude-code-transcripts all -o ./my-archive

# Include agent sessions
claude-code-transcripts all --include-agents
```

### Automatic export on session end

The `hook` and `render` subcommands together form a SessionEnd capture pipeline:

- `hook` reads a SessionEnd JSON payload from stdin, resolves the correct project name from the session's `cwd` (cwd-first, lossless, with the encoded `~/.claude/projects/` folder name as a fallback), files the raw `.jsonl` into the archive, fires desktop and (opt-in) voice notifications, then spawns `render` as a detached background process. Returns in milliseconds, so session shutdown is never blocked.
- `render` writes the HTML pages after the JSONL is filed. Normally spawned by `hook`, but works fine standalone for re-rendering a single session.

The pipeline is configured entirely via environment variables. The two most common to set:

- `TRANSCRIPT_EXPORT_DIR` - archive root (default: `~/claude-code-transcripts`).
- `TRANSCRIPT_OPEN_FOLDER=1` - reveal the session folder in the platform file manager after HTML is on disk (`open` on macOS, `xdg-open` on Linux).

The full list (including the opt-in `TRANSCRIPT_VOICE_URL` / `TRANSCRIPT_VOICE_ID` and the `SKIP_SESSION_END_HOOK` killswitch) is documented in [`docs/CLI.md#environment-variables`](docs/CLI.md#environment-variables). The pipeline contract (stdin payload schema, resolution order, skip rule, output layout) is in [`docs/CLI.md#hook`](docs/CLI.md#hook).

The natural way to wire this into Claude Code is the [companion plugin](https://github.com/CaptainCodeAU/gz-claude-code-plugins), which sets your env and pipes the SessionEnd payload to `claude-code-transcripts hook`. The plugin is a thin wrapper with no business logic, so the flagship CLI stays the single source of truth for naming, resolution, skip rules, notifications, and rendering.

### Reconciling orphan and drifted sessions

The reconciliation script handles two cleanup cases on a transcript archive.

**Orphan folders** (default mode): UUID-named session folders sitting at the archive root (from older plugin versions or manual exports) get folded into their correct project directories.

```bash
# Preview what would happen (safe, changes nothing):
uv run python scripts/reconcile_sessions.py --dry-run ~/CODE/my-claude-code-transcripts/

# Run for real (reconcile + rebuild indexes):
uv run python scripts/reconcile_sessions.py ~/CODE/my-claude-code-transcripts/

# Non-interactive (skip all confirmations):
uv run python scripts/reconcile_sessions.py --yes ~/CODE/my-claude-code-transcripts/
```

The script shows a move plan with action-verb headings, then prompts for each group:

- **Replace N sessions?** -- orphan has a larger JSONL than the existing copy (old copy backed up to `_DELETE/replaced/`)
- **Move N sessions?** -- new sessions for existing or new projects
- **Move N to _UNKNOWN?** -- sessions that can't be matched to any project
- **Move N duplicates to _DELETE?** -- duplicate orphans sent to `_DELETE/duplicates/`
- **Move N empty/unrecognized to _DELETE?** -- empty or non-session folders

**Drifted folders** (`--merge-drift`): sessions sitting in the wrong project folder (e.g., because an older buggy resolver produced a different display name) get re-routed using the session's own `cwd`. For each session: MOVE if the correct project has no collision; DEDUPE_IDENTICAL (soft-delete to `_DELETE/drift-dedupe/`) if a byte-equal copy already exists in the correct project; CONFLICT (untouched, reported) if the JSONL contents differ. Project folders left empty by the merge get drained to `_DELETE/drift-empty-projects/`.

```bash
# Preview the drift plan (no changes):
uv run python scripts/reconcile_sessions.py --merge-drift --dry-run ~/CODE/my-claude-code-transcripts/

# Apply (one combined confirmation for moves + dedupes + drains):
uv run python scripts/reconcile_sessions.py --merge-drift --yes ~/CODE/my-claude-code-transcripts/
```

Each group has its own confirmation prompt. Declining one skips it and continues to the next. **Nothing is permanently deleted**; unwanted folders are soft-deleted to `_DELETE/` subdirectories (recoverable). Session ages are derived from JSONL internal timestamps, not file modification dates. Reindexing only runs when the archive actually changed.

See [`docs/CLI.md#reconcile`](docs/CLI.md#reconcile) for the full flag reference (including `--fix-mtimes`) and the drift subsection, and [`docs/RECONCILE_FLOW.md`](docs/RECONCILE_FLOW.md) for decision flowcharts.

## Related projects

- [gz-claude-code-plugins](https://github.com/CaptainCodeAU/gz-claude-code-plugins) contains the **claude-transcript-exporter** plugin: a thin SessionEnd wrapper that pipes Claude Code's hook payload to `claude-code-transcripts hook`. The plugin carries no business logic of its own (this flagship CLI owns project-name resolution, the idempotency skip, JSONL filing, notifications, and the detached HTML render), so install it once and every session's transcript is exported to your archive directory without manual invocation, with nothing to drift out of sync.

## Development

To contribute to this tool, first checkout the code. You can run the tests using `uv run`:
```bash
cd claude-code-transcripts
uv run pytest
```
And run your local development copy of the tool like this:
```bash
uv run claude-code-transcripts --help
```

### Syncing with upstream

This fork tracks the upstream repo as a remote:
```bash
git remote add upstream https://github.com/simonw/claude-code-transcripts.git
git fetch upstream
```
