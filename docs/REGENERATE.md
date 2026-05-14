# Regenerating an archive

When the generator changes — for example, when [PR #4](https://github.com/CaptainCodeAU/claude-code-transcripts/pull/4) added the default dark palette and the floating theme toggle — already-generated `.html` files do **not** update on their own. Every CSS rule, JS snippet, and HTML element is inlined into each page at generation time, so bringing existing output forward means re-running the CLI over the corresponding source `.jsonl` files.

This document gives ready-made recipes for three scopes:

1. [A single session](#single-session)
2. [A single project (multiple sessions)](#single-project)
3. [The whole archive (all projects)](#whole-archive)

For per-flag detail on the commands referenced below, see [`CLI.md`](CLI.md).

## Single session

Use the `json` subcommand against the source `.jsonl` file.

Write directly into a chosen output folder:

```bash
claude-code-transcripts json \
  ~/.claude/projects/<project-folder>/<session-uuid>.jsonl \
  -o ~/my-claude-code-transcripts/<session-uuid>
```

Or auto-name the subdirectory by session UUID under a parent directory:

```bash
claude-code-transcripts json \
  ~/.claude/projects/<project-folder>/<session-uuid>.jsonl \
  -o ~/my-claude-code-transcripts -a
# writes to ~/my-claude-code-transcripts/<session-uuid>/
```

Default behavior opens the result in your browser. Pass `-o` (without `--open`) to suppress.

Useful add-ons:

- `--json` / `--no-json` — toggle whether the source `.jsonl` is copied alongside the rendered HTML (default: copy; pass `--no-json` to suppress).
- `--gist` — after generation, upload to a GitHub Gist and print a `gisthost.github.io` preview URL.
- `--repo owner/name` — set the GitHub repository for commit links (auto-detected from `git push` output in the session log if omitted).

See [`CLI.md#json`](CLI.md#json) for every flag.

## Single project

For one project containing many sessions, use the `all` subcommand and point `-s` at the **single project's folder** under `~/.claude/projects/`. `find_all_sessions` globs `**/*.jsonl` and groups each file by its parent folder — so pointing `-s` at one project subfolder produces an archive with exactly one project entry, exactly the way a full-archive run would, but limited to that one project.

```bash
claude-code-transcripts all \
  -s ~/.claude/projects/<project-folder> \
  -o ~/my-claude-code-transcripts
```

Preview first with `--dry-run`:

```bash
claude-code-transcripts all \
  -s ~/.claude/projects/<project-folder> \
  -o ~/my-claude-code-transcripts --dry-run
```

You'll see a header like `Found 1 projects with N sessions`, followed by the listing.

Useful add-ons:

- `--include-agents` — include `agent-*` session files (excluded by default).
- `-q, --quiet` — suppress per-batch progress output.
- `--open` — open the rebuilt archive's master `index.html` after generation. `all` does not auto-open the browser otherwise.

See [`CLI.md#all`](CLI.md#all) for every flag.

## Whole archive

To regenerate every project in `~/.claude/projects/`:

```bash
claude-code-transcripts all \
  -s ~/.claude/projects \
  -o ~/my-claude-code-transcripts
```

`-s` defaults to `~/.claude/projects`, so it can be omitted:

```bash
claude-code-transcripts all -o ~/my-claude-code-transcripts
```

The same `--dry-run`, `--include-agents`, `-q`, and `--open` add-ons apply. For very large archives, `-q` keeps the terminal quiet aside from a periodic "Processed N/total sessions" progress line.

## What gets overwritten

`all` writes into the output directory **in place**:

- Sessions present in both source and output → **refreshed** (existing HTML at the same paths is replaced).
- Sessions present in source but missing from output → **created**.
- Sessions present in output but no longer in source → **left untouched** as orphans on disk; they will not be linked from the rewritten indexes.
- The master `index.html` and every project's `index.html` are always rewritten from scratch based on the current source scan.

Pick an output directory you're comfortable being rewritten. To keep the previous archive intact for comparison, point `-o` at a brand-new directory.

## Verifying the regen worked

To confirm a generator-side change (e.g., PR #4's theme toggle) actually landed across the expected files, compare `id="theme-toggle"` matches to the total HTML count under the output:

```bash
root=~/my-claude-code-transcripts
total=$(find "$root" -type f -name "*.html" | wc -l | tr -d ' ')
withtoggle=$(grep -rl 'id="theme-toggle"' "$root" --include="*.html" | wc -l | tr -d ' ')
echo "with-toggle: $withtoggle of $total"
```

After a fresh `all` regen over the same source, the two counts should match (allowing for any failed sessions reported by the CLI).

Adapt the `grep` pattern to whatever generator-side change you're checking — a class name, a script tag, a specific CSS variable, etc.

## See also

- [`CLI.md`](CLI.md) — every flag for every subcommand
- [README](../README.md) — installation and high-level overview
