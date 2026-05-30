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

**Never start a Bash command with `cd`.** The harness hard-rejects any leading `cd` (it tells you to use `git -C <path>`, an absolute path, or `builtin cd`). This is a built-in Claude Code guard, not a repo hook. Treat the rejection as a signal to change the command *shape* (reach for `git -C` or absolute paths), not to retry the same `cd`-prefixed command. A rejected `cd` exits non-zero, so if it was batched with sibling calls it cancels all of them (see below): reads as a "stuck loop" but is really one repeated mistake.

**A non-zero exit from any Bash call cancels parallel siblings.** When multiple Bash calls are batched in one message, Claude Code aborts the others if any one exits non-zero. Never batch state-changing commands (`git add`/`commit`/`push`, file writes) in the same message as read-only probes: a probe that exits non-zero (e.g., `ls`/`grep`/`cat` on a missing path) silently cancels the mutation, so a commit can vanish with no error you would notice. Sequence mutations as their own calls. Prefer `find -print` (exits 0 when nothing matches) over `ls`/`grep` for existence checks.

## Editing files

Before editing a file, run `grep -cP '\t' <file>` to detect tab indentation. Match the file's indentation exactly (tabs vs spaces) or the Edit tool will fail.

## Deletion safety

`rm`, `cp`, and `mv` are shell-function wrappers with safety behavior (`rm` routes to trash; `cp`/`mv` default to `-i` overwrite prompts). **These wrappers are NEVER active in Bash tool calls.** Non-interactive shells skip `.zshrc`, so any `rm`/`cp`/`mv` here hits `/bin/rm` etc. directly: deletions are permanent and overwrites are silent. Always get explicit user confirmation before deleting or overwriting files. A `~/.config/safe-rm` denylist exists but does NOT protect against Bash-tool calls either.
