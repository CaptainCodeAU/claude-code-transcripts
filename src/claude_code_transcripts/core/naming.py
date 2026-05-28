"""Project-name derivation from Claude Code's encoded folder names.

Stdlib only. This is the single source of truth for turning an encoded
``~/.claude/projects/`` directory name into the archive's display name. The
plugin used to keep its own (buggy) copy of this; the redesign makes this the
only copy.
"""


def get_project_display_name(folder_name):
    """Convert encoded folder name to readable project name.

    Claude Code stores projects in folders like:
    - -home-user-projects-myproject -> myproject
    - -mnt-c-Users-name-Projects-app -> app

    For nested paths under common roots (home, projects, code, Users, etc.),
    extracts the meaningful project portion.
    """
    # Common path prefixes to strip
    prefixes_to_strip = [
        "-home-",
        "-mnt-c-Users-",
        "-mnt-c-users-",
        "-Users-",
    ]

    name = folder_name
    for prefix in prefixes_to_strip:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix) :]
            break

    # Split on dashes and find meaningful parts
    parts = name.split("-")

    # Common intermediate directories to skip
    skip_dirs = {"projects", "code", "repos", "src", "dev", "work", "documents"}

    # Find the first meaningful part (after skipping username and common dirs)
    meaningful_parts = []

    for i, part in enumerate(parts):
        if not part:
            continue
        if not meaningful_parts:
            if i == 0:
                remaining = [p.lower() for p in parts[i + 1 :]]
                if any(d in remaining for d in skip_dirs):
                    continue
            if part.lower() in skip_dirs:
                continue
        meaningful_parts.append(part)

    if meaningful_parts:
        return "-".join(meaningful_parts)

    # Fallback: return last non-empty part or original
    for part in reversed(parts):
        if part:
            return part
    return folder_name
