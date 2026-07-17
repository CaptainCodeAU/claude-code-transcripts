Default branch is `master`.

## Python and `uv`

Use `uv run python3` (not bare `python3`). A shell wrapper intercepts bare `python`/`python3` and version-specific calls (`py313`, `py312`) and redirects to `uv run`, but non-interactive Bash-tool shells skip `.zshrc`, so the wrapper is absent there. Always invoke `uv` directly.

Package management is `uv`, not pip/pipx:

- `uv add` / `uv remove` instead of `pip install` / `pip uninstall`.
- `uv tool` instead of `pipx`.
- In the Bash tool, `pip install` hits real pip (no wrapper). Call `uv` directly.

For standalone scripts that need third-party libs, use PEP 723 inline metadata (a `# /// script` block at the top). `uv run` resolves it automatically.

## Tests, formatting, and commits

Uses uv. Run tests like this:

    uv run pytest

Run the development version of the tool like this:

    uv run claude-code-transcripts --help

Always practice TDD: write a failing test, watch it fail, then make it pass.

Commit early and often. Commits should bundle the test, implementation, and documentation changes together.

Run Black to format code before you commit:

    uv run black .

## Node / JS package manager

Never use `npm` or `yarn`. Use `pnpm` (or `bun`). Pick by lockfile:

- `pnpm-lock.yaml` present: use pnpm.
- `bun.lockb` / `bun.lock` present: use bun.
- No lockfile: default to pnpm.
- Only `package-lock.json` or `yarn.lock` present: ignore them and use pnpm anyway (do not run npm/yarn to honor them).

For one-off package execution, prefer `pnpm dlx` over `npx`.

## Source-file encoding

Emit only ASCII punctuation in source code: straight quotes (`"` `'`), straight apostrophes, and hyphen-minus (`-`). Never write Unicode smart quotes (`" " ' '`), en/em dashes (`– —`), or other Unicode punctuation into code files. They pass type-checks but break the build at transform time (the JS/TS build rejects them), and hunting them down afterwards wastes a session. Unicode is fine in comments, docs, and string literals meant for display, but never in identifiers, keys, or code tokens.

## Shell

`NULL_GLOB` + `nonomatch` are set. Use `find -print` (not `ls glob*`) for file existence checks.

For port listing, use the `ports` function (OS-aware: `lsof` on macOS, `ss`/`netstat` on Linux/WSL) rather than calling those tools directly.

**Never start a Bash command with `cd`.** The harness hard-rejects any leading `cd` (it tells you to use `git -C <path>`, an absolute path, or `builtin cd`). This is a built-in Claude Code guard, not a repo hook. Treat the rejection as a signal to change the command _shape_ (reach for `git -C` or absolute paths), not to retry the same `cd`-prefixed command. A rejected `cd` exits non-zero, so if it was batched with sibling calls it cancels all of them (see below): reads as a "stuck loop" but is really one repeated mistake.

**A non-zero exit from any Bash call cancels parallel siblings.** A non-zero exit from any Bash call cancels the other tool calls batched in the same message (Claude Code aborts parallel siblings on error). Never batch state-changing commands (`git add`/`commit`/`push`, file writes) in the same message as read-only probes — a probe that exits non-zero (e.g. `ls`/`grep`/`cat` on a missing path) silently cancels the mutation, so a commit can vanish with no error you'd notice. Sequence mutations as their own calls, and prefer `find -print` over `ls`/`grep` for existence checks (it exits 0 on an empty match — but only when the search root exists; for a possibly-missing path use `test -e` or append `|| true`, per the Shell-section caveat above).

## Editing files

Before editing a file, run `grep -cP '\t' <file>` to detect tab indentation. Match the file's indentation exactly (tabs vs spaces) or the Edit tool will fail.

## Deletion safety

`rm`, `cp`, and `mv` are shell-function wrappers with safety behavior (`rm` routes to trash; `cp`/`mv` default to `-i` overwrite prompts). **These wrappers are usually ACTIVE in Bash tool calls**: Claude Code snapshots the interactive shell's functions to `~/.claude/shell-snapshots/` and sources that snapshot before every command, so the wrappers come along even though `.zshrc` itself is not read (verified for `rm` on 2026-06-08: `type -a rm` showed the snapshot function and a delete was recoverable from Trash; `cp`/`mv` presumably share the mechanism, untested). This is not guaranteed on every machine or session, so run `type rm` before trusting reversibility. The discipline does NOT change: always get explicit user confirmation before deleting or overwriting files, and treat Trash recovery as a safety net, never a license to delete. A `~/.config/safe-rm` denylist exists but does not protect Bash-tool calls.
