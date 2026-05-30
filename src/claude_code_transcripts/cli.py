"""CLI layer: argparse command surface and entry points.

Imports from the render/fetch/core layers plus notify/spawn and the stdlib
``picker``. The URL-fetch and gist helpers that raise CliError live here so the
fetch layer stays free of CLI concerns. This module is the only one that may
import httpx among the CLI helpers (BACKLOG 4.4); it no longer imports click or
questionary.
"""

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import httpx

from . import notify, spawn
from .core.archive import find_all_sessions
from .core.github import enrich_sessions_with_repos, filter_sessions_by_repo
from .core.idempotency import should_skip
from .core.resolve import resolve_project_name
from .core.summary import find_local_sessions
from .fetch.api import fetch_session, fetch_sessions, format_session_for_display
from .fetch.credentials import (
    get_access_token_from_keychain,
    get_org_uuid_from_config,
)
from . import picker
from .render.gist import inject_gist_preview_js
from .render.html import (
    generate_batch_html,
    generate_html,
    generate_html_from_session_data,
)

# Default archive root for the `hook` capture pipeline.
# Override with the TRANSCRIPT_EXPORT_DIR environment variable.
_DEFAULT_EXPORT_DIR = "~/claude-code-transcripts"

# The subcommands `local` is the default for (replaces click-default-group).
KNOWN_COMMANDS = {"local", "json", "web", "all", "render", "hook"}


class CliError(Exception):
    """A user-facing error. main() prints 'Error: <msg>' to stderr and exits 1.

    Replaces click.ClickException (same exit code and stderr behaviour).
    """


def create_gist(output_dir, public=False):
    """Create a GitHub gist from the HTML files in output_dir.

    Returns the gist ID on success, or raises CliError on failure.
    """
    output_dir = Path(output_dir)
    html_files = list(output_dir.glob("*.html"))
    if not html_files:
        raise CliError("No HTML files found to upload to gist.")

    # Build the gh gist create command
    # gh gist create file1 file2 ... --public/--private
    cmd = ["gh", "gist", "create"]
    cmd.extend(str(f) for f in sorted(html_files))
    if public:
        cmd.append("--public")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        # Output is the gist URL, e.g., https://gist.github.com/username/GIST_ID
        gist_url = result.stdout.strip()
        # Extract gist ID from URL
        gist_id = gist_url.rstrip("/").split("/")[-1]
        return gist_id, gist_url
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        raise CliError(f"Failed to create gist: {error_msg}")
    except FileNotFoundError:
        raise CliError(
            "gh CLI not found. Install it from https://cli.github.com/ and run 'gh auth login'."
        )


def local_cmd(args):
    """Select and convert a local Claude Code session to HTML."""
    output = args.output
    output_auto = args.output_auto
    repo = args.repo
    gist = args.gist
    include_json = args.include_json
    open_browser = args.open_browser
    limit = args.limit

    projects_folder = Path.home() / ".claude" / "projects"

    if not projects_folder.exists():
        print(f"Projects folder not found: {projects_folder}")
        print("No local Claude Code sessions available.")
        return

    print("Loading local sessions...")
    results = find_local_sessions(projects_folder, limit=limit)

    if not results:
        print("No local sessions found.")
        return

    # Build choices for the picker
    choices = []
    for filepath, summary in results:
        stat = filepath.stat()
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        size_kb = stat.st_size / 1024
        date_str = mod_time.strftime("%Y-%m-%d %H:%M")
        # Truncate summary if too long
        if len(summary) > 50:
            summary = summary[:47] + "..."
        display = f"{date_str}  {size_kb:5.0f} KB  {summary}"
        choices.append((display, filepath))

    selected = picker.select_from_list("Select a session to convert:", choices)

    if selected is None:
        print("No session selected.")
        return

    session_file = selected

    # Determine output directory and whether to open browser
    # If no -o specified, use temp dir and open browser by default
    auto_open = output is None and not gist and not output_auto
    if output_auto:
        # Use -o as parent dir (or current dir), with auto-named subdirectory
        parent_dir = Path(output) if output else Path(".")
        output = parent_dir / session_file.stem
    elif output is None:
        output = Path(tempfile.gettempdir()) / f"claude-session-{session_file.stem}"

    output = Path(output)
    generate_html(session_file, output, github_repo=repo)

    # Show output directory
    print(f"Output: {output.resolve()}")

    # Copy JSONL file to output directory if requested
    if include_json:
        output.mkdir(exist_ok=True)
        json_dest = output / session_file.name
        shutil.copy(session_file, json_dest)
        json_size_kb = json_dest.stat().st_size / 1024
        print(f"JSONL: {json_dest} ({json_size_kb:.1f} KB)")

    if gist:
        # Inject gist preview JS and create gist
        inject_gist_preview_js(output)
        print("Creating GitHub gist...")
        gist_id, gist_url = create_gist(output)
        preview_url = f"https://gisthost.github.io/?{gist_id}/index.html"
        print(f"Gist: {gist_url}")
        print(f"Preview: {preview_url}")

    if open_browser or auto_open:
        index_url = (output / "index.html").resolve().as_uri()
        webbrowser.open(index_url)


def is_url(path):
    """Check if a path is a URL (starts with http:// or https://)."""
    return path.startswith("http://") or path.startswith("https://")


def fetch_url_to_tempfile(url):
    """Fetch a URL and save to a temporary file.

    Returns the Path to the temporary file.
    Raises CliError on network errors.
    """
    try:
        response = httpx.get(url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.RequestError as e:
        raise CliError(f"Failed to fetch URL: {e}")
    except httpx.HTTPStatusError as e:
        raise CliError(
            f"Failed to fetch URL: {e.response.status_code} {e.response.reason_phrase}"
        )

    # Determine file extension from URL
    url_path = url.split("?")[0]  # Remove query params
    if url_path.endswith(".jsonl"):
        suffix = ".jsonl"
    elif url_path.endswith(".json"):
        suffix = ".json"
    else:
        suffix = ".jsonl"  # Default to JSONL

    # Extract a name from the URL for the temp file
    url_name = Path(url_path).stem or "session"

    temp_dir = Path(tempfile.gettempdir())
    temp_file = temp_dir / f"claude-url-{url_name}{suffix}"
    temp_file.write_text(response.text, encoding="utf-8")
    return temp_file


def json_cmd(args):
    """Convert a Claude Code session JSON/JSONL file or URL to HTML."""
    json_file = args.json_file
    output = args.output
    output_auto = args.output_auto
    repo = args.repo
    gist = args.gist
    include_json = args.include_json
    open_browser = args.open_browser

    # Handle URL input
    if is_url(json_file):
        print(f"Fetching {json_file}...")
        temp_file = fetch_url_to_tempfile(json_file)
        json_file_path = temp_file
        # Use URL path for naming
        url_name = Path(json_file.split("?")[0]).stem or "session"
    else:
        # Validate that local file exists
        json_file_path = Path(json_file)
        if not json_file_path.exists():
            raise CliError(f"File not found: {json_file}")
        url_name = None

    # Determine output directory and whether to open browser
    # If no -o specified, use temp dir and open browser by default
    auto_open = output is None and not gist and not output_auto
    if output_auto:
        # Use -o as parent dir (or current dir), with auto-named subdirectory
        parent_dir = Path(output) if output else Path(".")
        output = parent_dir / (url_name or json_file_path.stem)
    elif output is None:
        output = (
            Path(tempfile.gettempdir())
            / f"claude-session-{url_name or json_file_path.stem}"
        )

    output = Path(output)
    generate_html(json_file_path, output, github_repo=repo)

    # Show output directory
    print(f"Output: {output.resolve()}")

    # Copy JSON file to output directory if requested
    if include_json:
        output.mkdir(exist_ok=True)
        json_dest = output / json_file_path.name
        shutil.copy(json_file_path, json_dest)
        json_size_kb = json_dest.stat().st_size / 1024
        print(f"JSON: {json_dest} ({json_size_kb:.1f} KB)")

    if gist:
        # Inject gist preview JS and create gist
        inject_gist_preview_js(output)
        print("Creating GitHub gist...")
        gist_id, gist_url = create_gist(output)
        preview_url = f"https://gisthost.github.io/?{gist_id}/index.html"
        print(f"Gist: {gist_url}")
        print(f"Preview: {preview_url}")

    if open_browser or auto_open:
        index_url = (output / "index.html").resolve().as_uri()
        webbrowser.open(index_url)


def resolve_credentials(token, org_uuid):
    """Resolve token and org_uuid from arguments or auto-detect.

    Returns (token, org_uuid) tuple.
    Raises CliError if credentials cannot be resolved.
    """
    # Get token
    if token is None:
        token = get_access_token_from_keychain()
        if token is None:
            if platform.system() == "Darwin":
                raise CliError(
                    "Could not retrieve access token from macOS keychain. "
                    "Make sure you are logged into Claude Code, or provide --token."
                )
            else:
                raise CliError(
                    "On non-macOS platforms, you must provide --token with your access token."
                )

    # Get org UUID
    if org_uuid is None:
        org_uuid = get_org_uuid_from_config()
        if org_uuid is None:
            raise CliError(
                "Could not find organization UUID in ~/.claude.json. "
                "Provide --org-uuid with your organization UUID."
            )

    return token, org_uuid


def web_cmd(args):
    """Select and convert a web session from the Claude API to HTML.

    If SESSION_ID is not provided, displays an interactive picker to select a session.
    """
    session_id = args.session_id
    output = args.output
    output_auto = args.output_auto
    token = args.token
    org_uuid = args.org_uuid
    repo = args.repo
    gist = args.gist
    include_json = args.include_json
    open_browser = args.open_browser

    token, org_uuid = resolve_credentials(token, org_uuid)

    # If no session ID provided, show interactive picker
    if session_id is None:
        try:
            sessions_data = fetch_sessions(token, org_uuid)
        except httpx.HTTPStatusError as e:
            raise CliError(
                f"API request failed: {e.response.status_code} {e.response.text}"
            )
        except httpx.RequestError as e:
            raise CliError(f"Network error: {e}")

        sessions = sessions_data.get("data", [])
        if not sessions:
            raise CliError("No sessions found.")

        # Enrich sessions with repo information (extracted from session metadata)
        sessions = enrich_sessions_with_repos(sessions)

        # Filter by repo if specified
        if repo:
            sessions = filter_sessions_by_repo(sessions, repo)
            if not sessions:
                raise CliError(f"No sessions found for repo: {repo}")

        # Build choices for the picker
        choices = []
        for s in sessions:
            sid = s.get("id", "unknown")
            display = format_session_for_display(s)
            choices.append((display, sid))

        selected = picker.select_from_list("Select a session to import:", choices)

        if selected is None:
            # User cancelled
            raise CliError("No session selected.")

        session_id = selected

    # Fetch the session
    print(f"Fetching session {session_id}...")
    try:
        session_data = fetch_session(token, org_uuid, session_id)
    except httpx.HTTPStatusError as e:
        raise CliError(
            f"API request failed: {e.response.status_code} {e.response.text}"
        )
    except httpx.RequestError as e:
        raise CliError(f"Network error: {e}")

    # Determine output directory and whether to open browser
    # If no -o specified, use temp dir and open browser by default
    auto_open = output is None and not gist and not output_auto
    if output_auto:
        # Use -o as parent dir (or current dir), with auto-named subdirectory
        parent_dir = Path(output) if output else Path(".")
        output = parent_dir / session_id
    elif output is None:
        output = Path(tempfile.gettempdir()) / f"claude-session-{session_id}"

    output = Path(output)
    print(f"Generating HTML in {output}/...")
    generate_html_from_session_data(session_data, output, github_repo=repo)

    # Show output directory
    print(f"Output: {output.resolve()}")

    # Save JSON session data if requested
    if include_json:
        output.mkdir(exist_ok=True)
        json_dest = output / f"{session_id}.json"
        with open(json_dest, "w") as f:
            json.dump(session_data, f, indent=2)
        json_size_kb = json_dest.stat().st_size / 1024
        print(f"JSON: {json_dest} ({json_size_kb:.1f} KB)")

    if gist:
        # Inject gist preview JS and create gist
        inject_gist_preview_js(output)
        print("Creating GitHub gist...")
        gist_id, gist_url = create_gist(output)
        preview_url = f"https://gisthost.github.io/?{gist_id}/index.html"
        print(f"Gist: {gist_url}")
        print(f"Preview: {preview_url}")

    if open_browser or auto_open:
        index_url = (output / "index.html").resolve().as_uri()
        webbrowser.open(index_url)


def all_cmd(args):
    """Convert all local Claude Code sessions to a browsable HTML archive.

    Creates a directory structure with:
    - Master index listing all projects
    - Per-project pages listing sessions
    - Individual session transcripts
    """
    source = args.source
    output = args.output
    include_agents = args.include_agents
    dry_run = args.dry_run
    open_browser = args.open_browser
    quiet = args.quiet
    include_json = args.include_json

    # Default source folder
    if source is None:
        source = Path.home() / ".claude" / "projects"
    else:
        source = Path(source)

    if not source.exists():
        raise CliError(f"Source directory not found: {source}")

    output = Path(output)

    if not quiet:
        print(f"Scanning {source}...")

    projects = find_all_sessions(source, include_agents=include_agents)

    if not projects:
        if not quiet:
            print("No sessions found.")
        return

    # Calculate totals
    total_sessions = sum(len(p["sessions"]) for p in projects)

    if not quiet:
        print(f"Found {len(projects)} projects with {total_sessions} sessions")

    if dry_run:
        # Dry-run always outputs (it's the point of dry-run), but respects --quiet
        if not quiet:
            print("\nDry run - would convert:")
            for project in projects:
                print(f"\n  {project['name']} ({len(project['sessions'])} sessions)")
                for session in project["sessions"][:3]:  # Show first 3
                    mod_time = datetime.fromtimestamp(session["mtime"])
                    print(
                        f"    - {session['path'].stem} ({mod_time.strftime('%Y-%m-%d')})"
                    )
                if len(project["sessions"]) > 3:
                    print(f"    ... and {len(project['sessions']) - 3} more")
        return

    if not quiet:
        print(f"\nGenerating archive in {output}...")

    # Progress callback for non-quiet mode
    def on_progress(project_name, session_name, current, total):
        if not quiet and current % 10 == 0:
            print(f"  Processed {current}/{total} sessions...")

    # Generate the archive using the library function
    stats = generate_batch_html(
        source,
        output,
        include_agents=include_agents,
        include_json=include_json,
        progress_callback=on_progress,
    )

    # Report any failures
    if stats["failed_sessions"]:
        print(f"\nWarning: {len(stats['failed_sessions'])} session(s) failed:")
        for failure in stats["failed_sessions"]:
            print(f"  {failure['project']}/{failure['session']}: {failure['error']}")

    if not quiet:
        print(
            f"\nGenerated archive with {stats['total_projects']} projects, "
            f"{stats['total_sessions']} sessions"
        )
        print(f"Output: {output.resolve()}")

    if open_browser:
        index_url = (output / "index.html").resolve().as_uri()
        webbrowser.open(index_url)


def render_cmd(args):
    """Render an already-filed session's HTML (the background hook child)."""
    jsonl_file = args.jsonl_file
    output = Path(args.output)
    repo = args.repo
    try:
        generate_html(Path(jsonl_file), output, github_repo=repo)
    except Exception as e:
        # Detached child: a failure notification is the only signal that survives.
        notify.report(
            output.name, output.parent.name, "error", error=f"render failed: {e}"
        )
        raise
    print(f"Rendered: {output.resolve()}")
    # Opt-in: reveal the folder now that HTML is on disk. Doing this from the
    # render child (not the hook) avoids a race where the folder would open
    # before the HTML had been written.
    if os.environ.get("TRANSCRIPT_OPEN_FOLDER") == "1":
        notify.open_folder(str(output.resolve()))


def hook_cmd(args):
    """Export a session on SessionEnd (reads the hook JSON payload from stdin).

    Fast capture: resolve the project name (cwd-first), skip if unchanged, file
    the raw JSONL, notify success, then hand HTML rendering to a detached
    background child so session shutdown is never blocked.
    """
    if os.environ.get("SKIP_SESSION_END_HOOK") == "1":
        return

    start = time.time()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        notify.report("", None, "error", "invalid stdin payload")
        return

    session_id = payload.get("session_id", "")
    transcript_path = payload.get("transcript_path", "")
    payload_cwd = payload.get("cwd", "")

    if not transcript_path or not os.path.isfile(transcript_path):
        notify.report(session_id, None, "error", "transcript file missing")
        return

    project, source = resolve_project_name(transcript_path, payload_cwd)
    output_root = os.path.expanduser(
        os.environ.get("TRANSCRIPT_EXPORT_DIR") or _DEFAULT_EXPORT_DIR
    )
    uuid = Path(transcript_path).stem
    session_dir = os.path.join(output_root, project, uuid)

    if should_skip(transcript_path, session_dir, uuid):
        elapsed = int((time.time() - start) * 1000)
        notify.report(
            session_id,
            project,
            "skipped",
            "already exported (unchanged)",
            elapsed,
            source,
            payload_cwd,
        )
        # On skip the HTML already exists; open it now (the render child won't run).
        if os.environ.get("TRANSCRIPT_OPEN_FOLDER") == "1":
            notify.open_folder(session_dir)
        return

    try:
        os.makedirs(session_dir, exist_ok=True)
        dest = os.path.join(session_dir, uuid + ".jsonl")
        shutil.copy(transcript_path, dest)
    except OSError as e:
        elapsed = int((time.time() - start) * 1000)
        notify.report(
            session_id,
            project,
            "error",
            f"cannot file JSONL: {e}",
            elapsed,
            source,
            payload_cwd,
        )
        return

    elapsed = int((time.time() - start) * 1000)
    notify.report(session_id, project, "ok", "", elapsed, source, payload_cwd)
    spawn.spawn_render(dest, session_dir)


def existing_path(value):
    """argparse type: require an existing path (like click.Path(exists=True))."""
    if not os.path.exists(value):
        raise argparse.ArgumentTypeError(f"path does not exist: {value}")
    return value


def build_parser():
    """Build the argparse parser mirroring the former click command surface."""
    parser = argparse.ArgumentParser(
        prog="claude-code-transcripts",
        description="Convert Claude Code session JSON to mobile-friendly HTML pages.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=importlib.metadata.version("claude-code-transcripts"),
    )
    sub = parser.add_subparsers(dest="command")

    # local
    p = sub.add_parser(
        "local", help="Select and convert a local Claude Code session to HTML."
    )
    p.add_argument(
        "-o",
        "--output",
        help="Output directory. If not specified, writes to temp dir and opens in browser.",
    )
    p.add_argument(
        "-a",
        "--output-auto",
        action="store_true",
        help="Auto-name output subdirectory based on session filename (uses -o as parent, or current dir).",
    )
    p.add_argument(
        "--repo",
        help="GitHub repo (owner/name) for commit links. Auto-detected from git push output if not specified.",
    )
    p.add_argument(
        "--gist",
        action="store_true",
        help="Upload to GitHub Gist and output a gisthost.github.io URL.",
    )
    p.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=True,
        dest="include_json",
        help="Include the original JSONL session file in the output directory (default: include).",
    )
    p.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated index.html in your default browser (default if no -o specified).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of sessions to show (default: 10).",
    )
    p.set_defaults(func=local_cmd)

    # json
    p = sub.add_parser(
        "json", help="Convert a Claude Code session JSON/JSONL file or URL to HTML."
    )
    p.add_argument("json_file", help="Path or URL to a session JSON/JSONL file.")
    p.add_argument(
        "-o",
        "--output",
        help="Output directory. If not specified, writes to temp dir and opens in browser.",
    )
    p.add_argument(
        "-a",
        "--output-auto",
        action="store_true",
        help="Auto-name output subdirectory based on filename (uses -o as parent, or current dir).",
    )
    p.add_argument(
        "--repo",
        help="GitHub repo (owner/name) for commit links. Auto-detected from git push output if not specified.",
    )
    p.add_argument(
        "--gist",
        action="store_true",
        help="Upload to GitHub Gist and output a gisthost.github.io URL.",
    )
    p.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=True,
        dest="include_json",
        help="Include the original JSON session file in the output directory (default: include).",
    )
    p.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated index.html in your default browser (default if no -o specified).",
    )
    p.set_defaults(func=json_cmd)

    # web
    p = sub.add_parser(
        "web", help="Select and convert a web session from the Claude API to HTML."
    )
    p.add_argument(
        "session_id",
        nargs="?",
        default=None,
        help="Session ID to import. If omitted, shows an interactive picker.",
    )
    p.add_argument(
        "-o",
        "--output",
        help="Output directory. If not specified, writes to temp dir and opens in browser.",
    )
    p.add_argument(
        "-a",
        "--output-auto",
        action="store_true",
        help="Auto-name output subdirectory based on session ID (uses -o as parent, or current dir).",
    )
    p.add_argument(
        "--token", help="API access token (auto-detected from keychain on macOS)"
    )
    p.add_argument(
        "--org-uuid", help="Organization UUID (auto-detected from ~/.claude.json)"
    )
    p.add_argument(
        "--repo",
        help="GitHub repo (owner/name). Filters session list and sets default for commit links.",
    )
    p.add_argument(
        "--gist",
        action="store_true",
        help="Upload to GitHub Gist and output a gisthost.github.io URL.",
    )
    p.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=True,
        dest="include_json",
        help="Save the fetched JSON session data in the output directory (default: save).",
    )
    p.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated index.html in your default browser (default if no -o specified).",
    )
    p.set_defaults(func=web_cmd)

    # all
    p = sub.add_parser(
        "all",
        help="Convert all local Claude Code sessions to a browsable HTML archive.",
    )
    p.add_argument(
        "-s",
        "--source",
        type=existing_path,
        help="Source directory containing Claude projects (default: ~/.claude/projects).",
    )
    p.add_argument(
        "-o",
        "--output",
        default="./claude-archive",
        help="Output directory for the archive (default: ./claude-archive).",
    )
    p.add_argument(
        "--include-agents",
        action="store_true",
        help="Include agent-* session files (excluded by default).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be converted without creating files.",
    )
    p.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the generated archive in your default browser.",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress all output except errors.",
    )
    p.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=True,
        dest="include_json",
        help="Copy each session's original JSONL source into the output directory (default: include).",
    )
    p.set_defaults(func=all_cmd)

    # render
    p = sub.add_parser(
        "render",
        help="Render an already-filed session's HTML (the background hook child).",
    )
    p.add_argument("jsonl_file", help="Path to the filed JSONL session.")
    p.add_argument(
        "-o",
        "--output",
        required=True,
        help="Session output directory (already created by the hook).",
    )
    p.add_argument("--repo", help="GitHub repo (owner/name) for commit links.")
    p.set_defaults(func=render_cmd)

    # hook
    p = sub.add_parser(
        "hook",
        help="Export a session on SessionEnd (reads the hook JSON payload from stdin).",
    )
    p.set_defaults(func=hook_cmd)

    return parser


def parse_args_with_default_subcommand(parser, argv=None):
    """Parse argv, defaulting to the `local` subcommand (replaces DefaultGroup).

    Bare invocation -> `local`. A leading known subcommand or top-level flag
    (-h/--help/-v/--version) is passed through untouched; anything else is
    treated as arguments to `local`.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["local"]
    elif argv[0] not in KNOWN_COMMANDS and argv[0] not in (
        "-h",
        "--help",
        "-v",
        "--version",
    ):
        argv = ["local"] + argv
    return parser.parse_args(argv)


def main(argv=None):
    """Entry point: parse args, dispatch, and translate CliError to exit 1."""
    parser = build_parser()
    args = parse_args_with_default_subcommand(parser, argv)
    try:
        return args.func(args)
    except CliError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# Back-compat: the package exposes ``cli`` as the entry point object. It used to
# be the click group; it is now the same callable as ``main`` (accepts argv).
cli = main
