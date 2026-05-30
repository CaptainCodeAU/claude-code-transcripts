# CLI reference

Flag-by-flag reference for `claude-code-transcripts` — every command, every option, with defaults verified against the installed CLI.

For a high-level overview, see the project [README](../README.md). For ready-made recipes that re-run the generator over an existing archive (e.g., to roll out [PR #4](https://github.com/CaptainCodeAU/claude-code-transcripts/pull/4)'s dark-mode toggle to older sessions), see [`REGENERATE.md`](REGENERATE.md).

## Commands at a glance

| Command | Source of sessions | Default output dir | Auto-opens browser? |
|---|---|---|---|
| [`local`](#local-default) (default) | interactive picker over `~/.claude/projects` | temp dir | yes, unless `-o`, `--gist`, or `-a` is set |
| [`json`](#json) | a local path or `http(s)` URL | temp dir | yes, unless `-o`, `--gist`, or `-a` is set |
| [`web`](#web) | Claude API (`SESSION_ID` or interactive picker) | temp dir | yes, unless `-o`, `--gist`, or `-a` is set |
| [`all`](#all) | a directory tree of project folders | `./claude-archive` | no, only with explicit `--open` |
| [`hook`](#hook) | SessionEnd JSON payload on stdin | `$TRANSCRIPT_EXPORT_DIR` (default `~/claude-code-transcripts`) | no (opt-in folder reveal via `TRANSCRIPT_OPEN_FOLDER=1`) |
| [`render`](#render) | a specific session `.jsonl` (usually filed by `hook`) | required `-o` | no (opt-in folder reveal via `TRANSCRIPT_OPEN_FOLDER=1`) |
| [`reconcile`](#reconcile) (standalone script) | orphan UUID folders in an archive dir | in-place | no |

Global:

- `-v, --version` — print version and exit
- `--help` — every command (and the top-level command) supports `--help`

## `local` (default)

Synopsis:

```bash
claude-code-transcripts [local] [OPTIONS]
```

Pick a session from `~/.claude/projects/` via an interactive picker and convert it. This is the **default** subcommand: it runs when you invoke `claude-code-transcripts` with no subcommand.

> The picker is a built-in, dependency-free arrow-key list: Up/Down (or `k`/`j`) to move, Enter to select, `q` or Esc to cancel. It is POSIX-only and requires a real terminal (there is no non-TTY fallback). The `web` picker behaves the same.

| Option | Type | Default | Description |
|---|---|---|---|
| `-o, --output PATH` | path | unset (temp dir, auto-open) | Output directory for the generated HTML. |
| `-a, --output-auto` | flag | off | Auto-name an output subdirectory by session filename. Use with `-o` as the parent, or alone (current directory). |
| `--repo TEXT` | `owner/name` | auto-detected from `git push` output in the session log | GitHub repository for commit links. |
| `--gist` | flag | off | After generation, upload HTML to a GitHub Gist and print a `gisthost.github.io` preview URL. |
| `--json` / `--no-json` | flag | on | Copy the original `.jsonl` source into the output directory alongside the HTML (default: on; pass `--no-json` to suppress). |
| `--open` | flag | implicit when no `-o`, no `--gist`, no `-a` | Open `index.html` in your default browser. |
| `--limit INTEGER` | int | `10` | Maximum number of sessions shown in the picker. |
| `--help` | flag | — | Show command help and exit. |

Sessions whose summary is `"warmup"` or `"(no summary)"` are filtered out of the picker.

Default output path when nothing is specified:

```
$TMPDIR/claude-session-<session-uuid>/
```

## `json`

Synopsis:

```bash
claude-code-transcripts json [OPTIONS] JSON_FILE
```

Convert a specific session file, or a URL pointing at one. URLs are fetched to a temporary `.jsonl` / `.json` file before parsing.

Positional argument:

- `JSON_FILE` — a local path (`.json` or `.jsonl`) **or** an `http://` / `https://` URL.

| Option | Type | Default | Description |
|---|---|---|---|
| `-o, --output PATH` | path | unset (temp dir, auto-open) | Output directory. |
| `-a, --output-auto` | flag | off | Auto-name an output subdirectory by filename stem (or URL stem). |
| `--repo TEXT` | `owner/name` | auto-detected from `git push` output in the session log | GitHub repository for commit links. |
| `--gist` | flag | off | Upload to a Gist and print preview URL. |
| `--json` / `--no-json` | flag | on | Copy the source file into the output directory (default: on; pass `--no-json` to suppress). |
| `--open` | flag | implicit when no `-o`, no `--gist`, no `-a` | Open `index.html` after generation. |
| `--help` | flag | — | Show command help and exit. |

Default output path:

```
$TMPDIR/claude-session-<file-or-url-stem>/
```

## `web`

Synopsis:

```bash
claude-code-transcripts web [OPTIONS] [SESSION_ID]
```

Fetch a session from the Claude API. If `SESSION_ID` is omitted, an interactive picker lists your recent web sessions.

Positional argument:

- `SESSION_ID` — optional. If given, fetches that session directly.

| Option | Type | Default | Description |
|---|---|---|---|
| `-o, --output PATH` | path | unset (temp dir, auto-open) | Output directory. |
| `-a, --output-auto` | flag | off | Auto-name an output subdirectory by `SESSION_ID`. |
| `--token TEXT` | string | macOS keychain | API access token. |
| `--org-uuid TEXT` | UUID string | read from `~/.claude.json` | Organization UUID. |
| `--repo TEXT` | `owner/name` | unset | Filters the picker to that repo and sets the default for commit links. |
| `--gist` | flag | off | Upload to a Gist and print preview URL. |
| `--json` / `--no-json` | flag | on | Save fetched JSON as `<SESSION_ID>.json` in the output directory (default: on; pass `--no-json` to suppress). |
| `--open` | flag | implicit when no `-o`, no `--gist`, no `-a` | Open `index.html` after generation. |
| `--help` | flag | — | Show command help and exit. |

Credential resolution order:

1. **Token** — explicit `--token` flag → macOS keychain entry → error on non-macOS without `--token`.
2. **Org UUID** — explicit `--org-uuid` flag → `~/.claude.json` lookup → error if neither.

Default output path:

```
$TMPDIR/claude-session-<session-id>/
```

## `all`

Synopsis:

```bash
claude-code-transcripts all [OPTIONS]
```

Walk a folder of Claude Code projects and produce a browsable archive: a master index linking to per-project indexes linking to per-session transcripts. No interactive picker, no positional argument.

| Option | Type | Default | Description |
|---|---|---|---|
| `-s, --source PATH` | existing path | `~/.claude/projects` | Source folder to scan recursively for `*.jsonl` sessions. Pointing this at a single project subfolder produces an archive containing exactly one project — see [`REGENERATE.md`](REGENERATE.md#single-project). |
| `-o, --output PATH` | path | `./claude-archive` | Output directory for the archive. |
| `--include-agents` | flag | off | Include `agent-*` session files (excluded by default). |
| `--dry-run` | flag | off | Print which projects/sessions would be converted; write nothing. |
| `--open` | flag | off | Open the master `index.html` after generation. **Note:** `all` does **not** auto-open the browser; `--open` is the only way. |
| `-q, --quiet` | flag | off | Suppress informational output (errors still print; `--dry-run` still prints its listing). |
| `--json` / `--no-json` | flag | on | Copy each session's source `.jsonl` into its output directory alongside the rendered HTML (default: on; pass `--no-json` to suppress). |
| `--help` | flag | — | Show command help and exit. |

Source scan uses `<source>.glob("**/*.jsonl")` and groups each session by its parent folder (the "project"). Sessions with summary `"warmup"` or `"(no summary)"` are filtered out. Unless `--include-agents` is set, files starting with `agent-` are skipped.

Output structure:

```
<output>/
├── index.html                # master: list of projects
├── <project-display-name>/
│   ├── index.html            # project: list of sessions
│   └── <session-uuid>/
│       ├── index.html        # session index (timeline)
│       ├── page-001.html     # paginated transcript pages
│       └── page-NNN.html
└── ...
```

`<project-display-name>` is derived from the source folder name (e.g., `-Users-alice-CODE-MyOrg-my-project` becomes `MyOrg-my-project`).

Default output path:

```
./claude-archive/
```

## Flags shared by `local`, `json`, and `web`

These three single-session commands share the same output, repo, gist, json, and open flags:

- `-o, --output PATH`
- `-a, --output-auto`
- `--repo TEXT`
- `--gist`
- `--json` / `--no-json`
- `--open`

`all` has its own surface — `-s`, `-o`, `--include-agents`, `--dry-run`, `--open`, `-q`.

## Auto-open browser logic

For `local`, `json`, and `web`, the browser auto-opens `index.html` when **all** of these hold at invocation time:

- `-o` is omitted
- `--gist` is not set
- `-a` is not set

Pass `--open` explicitly to force a browser open when one of the above does not hold. For `all`, the browser never auto-opens — `--open` is the only way.

## Examples

Quickest path — pick a recent session, open it in your browser:

```bash
claude-code-transcripts
```

Convert a specific JSONL file to a chosen output directory:

```bash
claude-code-transcripts json \
  ~/.claude/projects/<project-folder>/<session>.jsonl \
  -o ./my-archive
```

Auto-name an output subdirectory under a parent:

```bash
claude-code-transcripts json \
  ~/.claude/projects/<project-folder>/<session>.jsonl \
  -o ./my-archives -a
# writes to ./my-archives/<session-stem>/
```

Fetch a web session by ID and publish as a Gist preview:

```bash
claude-code-transcripts web 8b2f...abc --gist
```

Build a fresh full archive of every local project:

```bash
claude-code-transcripts all -s ~/.claude/projects -o ~/my-claude-code-transcripts
```

Preview an archive build without writing files:

```bash
claude-code-transcripts all -s ~/.claude/projects -o ~/my-claude-code-transcripts --dry-run
```

## `hook`

Synopsis:

```bash
claude-code-transcripts hook < SESSION_END_PAYLOAD.json
```

Capture a session at SessionEnd: read the hook payload from stdin, resolve the
correct project name from the session's `cwd` (cwd-first, lossless), file the
raw `.jsonl` into the archive, fire desktop/voice notifications, and spawn a
detached HTML render so session shutdown is never blocked. Returns in
milliseconds.

Designed to be wired into a Claude Code SessionEnd hook (typically via a thin
plugin wrapper). Takes no CLI options; everything comes from the stdin payload
plus a small set of environment variables (see
[Environment variables](#environment-variables)).

Stdin payload (JSON object):

| Field | Required | Description |
|---|---|---|
| `session_id` | yes | Used in log entries and failure notifications. |
| `transcript_path` | yes | Absolute path to the source `.jsonl` Claude Code wrote. |
| `cwd` | optional | The session's working directory. When present (the usual case), used cwd-first to derive the correct project name. |

Project-name resolution order (first match wins):

1. payload `cwd`, encoded the same lossy way Claude Code does (`/`, `_`, `.` become `-`), then run through `get_project_display_name` (label `payload_cwd`).
2. The first non-empty `cwd` field inside the JSONL itself (label `jsonl_cwd`).
3. The parent folder of `transcript_path` (the lossy `~/.claude/projects/` encoded name, label `transcript_path`).
4. `_unresolved/` (label `unresolved`), last resort.

Skip rule: a session is skipped if its target session directory already has
`index.html` AND a `<uuid>.jsonl` whose size matches the source (JSONL is
append-only, so equal size means unchanged).

Output layout:

```
<TRANSCRIPT_EXPORT_DIR>/<project>/<uuid>/
├── <uuid>.jsonl       # raw transcript copy (written by hook)
├── index.html         # written by the detached render child
└── page-NNN.html
```

Behavior summary:

| Outcome | Notify | Render spawned? | Folder revealed (if `TRANSCRIPT_OPEN_FOLDER=1`) |
|---|---|---|---|
| Filed (new) | `ok` | yes | by the render child after HTML is on disk |
| Skipped (unchanged) | `skipped` | no | by the hook immediately (HTML already exists) |
| Bad payload / missing transcript / filing error | `error` | no | no |

Set `SKIP_SESSION_END_HOOK=1` to make `hook` no-op immediately (useful during
in-progress automation that would otherwise trigger SessionEnd noise).

## `render`

Synopsis:

```bash
claude-code-transcripts render JSONL_FILE -o OUTPUT [--repo OWNER/NAME]
```

Render a single session's HTML into an existing output directory. This is the
command that `hook` spawns in the background; you rarely call it directly, but
it works fine standalone for re-rendering one session.

Positional argument:

- `JSONL_FILE`, path to a session `.jsonl`.

| Option | Type | Default | Description |
|---|---|---|---|
| `-o, --output PATH` | path | (required) | Session output directory. Normally already created by `hook`. |
| `--repo TEXT` | `owner/name` | auto-detected from `git push` in the log | GitHub repository for commit links. |
| `--help` | flag | -- | Show command help and exit. |

When `TRANSCRIPT_OPEN_FOLDER=1`, reveals the output folder after HTML is on
disk (the render-side timing avoids the race where opening at hook-return
would show only the raw JSONL).

## Environment variables

The capture pipeline and a couple of CLI behaviors read environment variables.
Set them in your shell, your `hooks.json` command line, or (most commonly) in
the plugin wrapper that delegates to `claude-code-transcripts hook`.

| Variable | Used by | Default | Description |
|---|---|---|---|
| `TRANSCRIPT_EXPORT_DIR` | `hook` | `~/claude-code-transcripts` | Archive root for the capture pipeline. Expanded with `~`. |
| `SKIP_SESSION_END_HOOK` | `hook` | unset | When `1`, `hook` returns immediately and does nothing. |
| `TRANSCRIPT_VOICE_URL` | `hook`, `render` (via notify) | unset | Opt-in voice notification. When set, success/failure events POST a JSON payload to this URL via `curl --connect-timeout 2`. Unset means voice is silent. |
| `TRANSCRIPT_VOICE_ID` | `hook`, `render` (via notify) | unset | Optional voice identifier; included in the POST when `TRANSCRIPT_VOICE_URL` is set. |
| `TRANSCRIPT_OPEN_FOLDER` | `hook` (on skip), `render` (after success) | unset | Opt-in. When `1`, opens the session output folder in the platform file manager (`open` on macOS, `xdg-open` on Linux). |

All capture-pipeline env vars are best-effort: an unavailable voice endpoint or
missing `open`/`xdg-open` is swallowed silently so a SessionEnd never fails on
unrelated infrastructure.

## `reconcile`

Synopsis:

```bash
uv run python scripts/reconcile_sessions.py [OPTIONS] PATH
```

Organize orphan UUID-named session folders sitting at the root of an archive directory into their correct project subdirectories. This is a standalone Python script (not a CLI subcommand) that imports from the `claude_code_transcripts` package.

Positional argument:

- `PATH` — path to the transcript archive directory (e.g., `~/CODE/my-claude-code-transcripts/`).

| Option | Type | Default | Description |
|---|---|---|---|
| `--dry-run` | flag | off | Show the move plan without making changes. Reindexing is also skipped. |
| `--no-reindex` | flag | off | Skip rebuilding project and master `index.html` pages after reconciliation. By default, all indexes are rebuilt. |
| `--yes` | flag | off | Skip all interactive confirmations. |
| `--verbose, -v` | flag | off | Show detailed error output on failures. |
| `--merge-drift` | flag | off | Additionally re-derive each session's correct project from its JSONL `cwd` and merge drifted folders. See [Drift merge mode](#drift-merge-mode) below. |
| `--fix-mtimes` | flag | off | Correct file modification times across the entire archive to match each JSONL's last internal timestamp. Useful after restoring from backups or moving files. |
| `--cleanup` | flag | off | Legacy flag, no longer required. Duplicate/empty cleanup prompts now appear automatically. |
| `--help` | flag | -- | Show command help and exit. |

### How it works

1. **Scan** the archive root for UUID-named directories (orphans).
2. **Categorize** each orphan: has JSONL, HTML only, empty, or unrecognized files.
3. **Derive project** from JSONL `cwd` field or HTML file path references. Sessions that can't be matched go to `_UNKNOWN/`.
4. **Compare duplicates** when the target already exists: compares JSONL file sizes (larger = more complete, since JSONL is append-only). If the orphan is larger, it replaces the organized copy (old copy backed up to `_DELETE/replaced/`). If sizes match, the orphan is marked as already organized.
5. **Show move plan** with action-verb headings ("Replace N sessions?", "Move N sessions?", "Move N duplicates to _DELETE?"). Each entry shows the target project, size delta (for replacements), and relative age derived from JSONL internal timestamps. A summary shows per-destination totals.
6. **Prompt per group**: each group has its own confirmation. Declining one skips it and continues to the next. Duplicate orphans, empty folders, and unrecognized folders are prompted for soft-delete to `_DELETE/`.
7. **Rebuild indexes** (only if the archive changed): scans the archive and regenerates project and master `index.html` pages. Skipped if `--dry-run`, `--no-reindex`, or no files were moved/replaced/deleted. Only indexes that actually changed are reported, with size deltas.

Nothing is permanently deleted. Unwanted folders are moved to `_DELETE/`
subdirectories: `duplicates/`, `empty/`, `unrecognized/`, `replaced/` (orphan
path), and `drift-dedupe/<wrong-project>/`, `drift-empty-projects/`
([drift mode](#drift-merge-mode)). If a name collision occurs, a suffix (`-1`,
`-2`, etc.) is appended.

### Drift merge mode

Pass `--merge-drift` to additionally reconcile *drifted project folders*: cases
where a session sits in `Owner-foo-bar/` but its JSONL `cwd` actually derives
to `Owner-foo-baz/`. This is a different problem from orphan handling (which
moves stray UUID folders into projects); drift moves sessions *between*
projects when the parent folder name is wrong.

For each session under each non-`_` project folder, drift mode re-derives the
correct project name from the session's `cwd` via the fixed
`get_project_display_name` and picks one of:

- **MOVE**: no collision in the correct project, so the session is relocated there.
- **DEDUPE_IDENTICAL**: a session with the same UUID and a byte-equal JSONL
  already exists in the correct project, so the wrong copy is soft-deleted to
  `_DELETE/drift-dedupe/<wrong-project>/`.
- **CONFLICT**: a session with the same UUID exists in the correct project but
  the JSONL contents differ. Both copies are left in place and reported. Drift
  mode never auto-resolves a content conflict (honors the same
  nothing-is-permanently-deleted rule that governs the rest of the script).

After per-session classification, any non-`_` project folder that no longer
contains session data (just `index.html` or dotfiles like `.DS_Store`) is
soft-deleted to `_DELETE/drift-empty-projects/`. The pass is idempotent: a
re-run with no actual drift left will still drain any leftover empty folders
from a prior partial run.

Sessions whose JSONL has no `cwd` field are skipped with a logged reason and
left in place.

Dry-run previews include both the move/dedupe/conflict plan and the count of
empty-folder candidates. The apply path prompts with a combined "Apply N drift
actions and drain M empty folders?" confirmation (use `--yes` to skip).

### Examples

```bash
# Preview what would happen (no changes made)
uv run python scripts/reconcile_sessions.py --dry-run ~/CODE/my-claude-code-transcripts/

# Run for real (reconcile + rebuild indexes)
uv run python scripts/reconcile_sessions.py ~/CODE/my-claude-code-transcripts/

# Non-interactive (skip all confirmations)
uv run python scripts/reconcile_sessions.py --yes ~/CODE/my-claude-code-transcripts/

# Run without rebuilding indexes
uv run python scripts/reconcile_sessions.py --no-reindex ~/CODE/my-claude-code-transcripts/

# Drift mode: preview project-name drift remediation (re-derives from JSONL cwd)
uv run python scripts/reconcile_sessions.py --merge-drift --dry-run ~/CODE/my-claude-code-transcripts/

# Drift mode: apply (moves uniques, soft-deletes byte-equal dupes, drains empty projects)
uv run python scripts/reconcile_sessions.py --merge-drift --yes ~/CODE/my-claude-code-transcripts/
```

## See also

- [README](../README.md) — installation and high-level overview
- [`REGENERATE.md`](REGENERATE.md) — recipes for re-running the generator over an existing archive
