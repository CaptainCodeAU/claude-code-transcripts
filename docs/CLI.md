# CLI reference

Flag-by-flag reference for `claude-code-transcripts` — every command, every option, with defaults verified against the installed CLI.

For a high-level overview, see the project [README](../README.md). For ready-made recipes that re-run the generator over an existing archive (e.g., to roll out [PR #4](https://github.com/CaptainCodeAU/claude-code-transcripts/pull/4)'s dark-mode toggle to older sessions), see [`REGENERATE.md`](REGENERATE.md).

## Commands at a glance

| Command | Source of sessions | Default output dir | Auto-opens browser? |
|---|---|---|---|
| [`local`](#local-default) (default) | interactive picker over `~/.claude/projects` | temp dir | yes — unless `-o`, `--gist`, or `-a` is set |
| [`json`](#json) | a local path or `http(s)` URL | temp dir | yes — unless `-o`, `--gist`, or `-a` is set |
| [`web`](#web) | Claude API (`SESSION_ID` or interactive picker) | temp dir | yes — unless `-o`, `--gist`, or `-a` is set |
| [`all`](#all) | a directory tree of project folders | `./claude-archive` | no — only with explicit `--open` |

Global:

- `-v, --version` — print version and exit
- `--help` — every command (and the top-level command) supports `--help`

## `local` (default)

Synopsis:

```bash
claude-code-transcripts [local] [OPTIONS]
```

Pick a session from `~/.claude/projects/` via an interactive picker and convert it. This is the **default** subcommand: it runs when you invoke `claude-code-transcripts` with no subcommand.

| Option | Type | Default | Description |
|---|---|---|---|
| `-o, --output PATH` | path | unset (temp dir, auto-open) | Output directory for the generated HTML. |
| `-a, --output-auto` | flag | off | Auto-name an output subdirectory by session filename. Use with `-o` as the parent, or alone (current directory). |
| `--repo TEXT` | `owner/name` | auto-detected from `git push` output in the session log | GitHub repository for commit links. |
| `--gist` | flag | off | After generation, upload HTML to a GitHub Gist and print a `gisthost.github.io` preview URL. |
| `--json` | flag | off | Copy the original `.jsonl` source into the output directory alongside the HTML. |
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
| `--json` | flag | off | Copy the source file into the output directory. |
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
| `--json` | flag | off | Save fetched JSON as `<SESSION_ID>.json` in the output directory. |
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

`<project-display-name>` is derived from the source folder name (e.g., `-Users-fonzarelli-CODE-CaptainCodeAU-claude-code-transcripts` becomes `CaptainCodeAU-claude-transcripts`).

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
- `--json`
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

## See also

- [README](../README.md) — installation and high-level overview
- [`REGENERATE.md`](REGENERATE.md) — recipes for re-running the generator over an existing archive
