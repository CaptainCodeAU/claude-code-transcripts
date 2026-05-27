# migrate_project.py

Migrate a repo to its correct username-based directory and update all associated Claude Code project directories, memory files, and transcript archive folders to match.

## Quick Start

```bash
# Preview what would happen (always do this first):
uv run python scripts/migrate_project.py --dry-run ~/CODE/Legacy/my-project

# Execute the migration:
uv run python scripts/migrate_project.py ~/CODE/Legacy/my-project

# Auto-confirm all prompts:
uv run python scripts/migrate_project.py --yes ~/CODE/Legacy/my-project
```

## What It Does

Given a repo path, the script:

1. Reads the git remote URL to find the GitHub owner (e.g., `MyOrg`)
2. Checks `~/.ssh/config.local` to determine if this is your own account
3. Computes the correct directory: `{os_root}/{owner}/{repo_name}`
4. Moves the repo folder
5. Renames all Claude Code project directories under `~/.claude/projects/`
6. Updates path references inside memory files
7. Renames the transcript archive folder (Mac only, or with `--archive-path`)

## CLI Reference

```
uv run python scripts/migrate_project.py [--dry-run] [--yes] [--archive-path PATH] <project-path>
```

| Flag | Description |
|------|-------------|
| `<project-path>` | Path to the repo to migrate (required) |
| `--dry-run` | Show migration plan without executing or prompting |
| `--yes` | Auto-confirm all interactive prompts |
| `--archive-path PATH` | Transcript archive directory. Defaults to `~/CODE/my-claude-code-transcripts/` on Mac. On Linux/WSL, skipped unless this flag is provided |

## How It Works

### OS Root Detection

| OS | Root | Detection |
|----|------|-----------|
| macOS | `~/CODE/` | `uname == Darwin` |
| Linux/WSL | `~/repos/` | Everything else |

This is a hardcoded convention, not configurable.

### Own Account Detection

The script parses `~/.ssh/config.local` for `Host git-*` entries. These are SSH aliases that route to GitHub for your own accounts:

```
Host git-acme      -> MyOrg
Host git-other     -> AnotherOrg
```

If the repo's remote hostname matches one of these aliases (e.g., `git-acme:MyOrg/repo.git`), the script knows it's your own account and uses the owner name from the URL as the target subfolder.

**Prerequisite:** All owned repos must use `git-*` SSH aliases as their remote hostname, not raw `git@github.com:`. Normalize any old-format remotes first:

```bash
git remote set-url origin git-acme:MyOrg/repo-name.git
```

### 3rdParty Classification

If the remote hostname doesn't match any `Host git-*` alias, the script prompts:

```
Owner 'microsoft' is not a known account.
Move to 3rdParty/? [Y/n/custom folder name]
```

With `--yes`, unrecognized owners automatically go to `3rdParty/`.

### Remote URL Formats

The script parses these formats:

| Format | Example | Host | Owner |
|--------|---------|------|-------|
| SSH alias | `git-acme:MyOrg/repo.git` | `git-acme` | `MyOrg` |
| SSH standard | `git@github.com:Owner/repo.git` | `github.com` | `Owner` |
| HTTPS | `https://github.com/Owner/repo.git` | `github.com` | `Owner` |

The `.git` suffix is stripped from repo names. Owner case is preserved from the URL.

### Execution Order

When not in dry-run mode, operations happen in this order:

1. Create target parent directory (`mkdir -p`)
2. Move the repo folder
3. Update memory file contents (while Claude dirs still have old names)
4. Rename Claude project directories
5. Rename transcript archive folder (if applicable)

Memory files are updated before directory renames so that file paths are stable during the scan.

### What Gets Updated in Memory Files

Three forms of path reference are replaced:

| Form | Example |
|------|---------|
| Absolute | `/Users/alice/CODE/Legacy/my-project` |
| Tilde | `~/CODE/Legacy/my-project` |
| Encoded | `-Users-alice-CODE-Legacy-my-project` |

Session log files (`.jsonl`) are **never modified**. They are historical records. The reconcile script uses the `cwd` field inside JSONL files to map sessions to projects and handles old-to-new path mapping independently.

## Edge Cases

### Repo Already in Correct Location

```
Already in correct location: ~/CODE/MyOrg/my-project
```

The script exits cleanly with code 0.

### Target Directory Exists

If the target exists and contains files, the script errors:

```
Error: target directory already exists and is not empty:
  ~/CODE/MyOrg/myrepo
```

If the target exists but is empty, it's removed and the move proceeds.

### Subproject Directories

When Claude Code is launched from a subdirectory (e.g., `~/repos/my-app/cli/`), it creates a separate project directory (e.g., `-home-user-repos-my-app-cli`). The script finds all directories matching the old encoded prefix, including subproject contexts, and renames them all.

### No Claude Project Directories Found

If no matching directories exist under `~/.claude/projects/`, the script warns but continues. The repo may never have been used with Claude Code.

### No Archive Folder

If the transcript archive doesn't contain a folder for this project, the archive rename step is skipped silently.

### Archive Names That Don't Change

If the old and new display names are identical (e.g., moving between directories at the same depth), the archive rename step is skipped.

### Not a Git Repository

```
Error: /path/to/folder is not a git repository.
```

The path must contain a `.git/` directory (or `.git` file for worktrees).

### Subdirectory of a Repo

```
Error: /path/to/repo/src is a subdirectory, not the repo root.
  Repo root is: /path/to/repo
```

The script only accepts the repo root, not subdirectories within it.

### No Origin Remote

```
Error: no origin remote found.
```

The repo must have a remote named `origin` with a parseable URL.

### Cross-Filesystem Moves

The script uses `shutil.move` which handles cross-filesystem moves (copies then deletes if a direct rename fails across mount points).

## Example Output

```
Migration plan for: my-project

  Repo move:
    ~/CODE/Legacy/my-project
    -> ~/CODE/MyOrg/my-project

  Claude project directories: 1 to rename
    -Users-alice-CODE-Legacy-my-project
    -> -Users-alice-CODE-MyOrg-my-project
    (12 memory files, 150 session logs)

  Memory file updates: 3 files with 4 path references

  Archive folder rename:
    Legacy-my-project/
    -> MyOrg-my-project/

Proceed? [y/N]
```
