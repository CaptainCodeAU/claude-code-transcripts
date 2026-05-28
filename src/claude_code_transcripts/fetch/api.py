"""Anthropic Sessions API client for the fetch layer."""

import httpx

API_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


def get_api_headers(token, org_uuid):
    """Build API request headers."""
    return {
        "Authorization": f"Bearer {token}",
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
        "x-organization-uuid": org_uuid,
    }


def fetch_sessions(token, org_uuid):
    """Fetch list of sessions from the API.

    Uses the Sessions API (GET /v1/sessions) with the required beta header.
    Returns the sessions data as a dict with 'data' key containing session list.
    Raises httpx.HTTPError on network/API errors.
    """
    headers = get_api_headers(token, org_uuid)
    headers["anthropic-beta"] = "ccr-byoc-2025-07-29"
    response = httpx.get(f"{API_BASE_URL}/sessions", headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.json()


def fetch_session(token, org_uuid, session_id):
    """Fetch a specific session's transcript from the API.

    Uses two endpoints:
    1. GET /v1/sessions/{id} for session metadata (with beta header)
    2. GET /v1/code/sessions/{id}/teleport-events for the transcript (paginated)

    Falls back to the legacy /v1/session_ingress/session/{id} endpoint if
    teleport-events returns 404 (migration period).

    Returns the session data as a dict with 'loglines' key.
    Raises httpx.HTTPError on network/API errors.
    """
    headers = get_api_headers(token, org_uuid)
    headers["anthropic-beta"] = "ccr-byoc-2025-07-29"

    # First try the new teleport-events endpoint (paginated)
    loglines = _fetch_teleport_events(token, org_uuid, session_id)

    if loglines is None:
        # Fall back to legacy session_ingress endpoint
        legacy_headers = get_api_headers(token, org_uuid)
        response = httpx.get(
            f"{API_BASE_URL}/session_ingress/session/{session_id}",
            headers=legacy_headers,
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()

    return {"loglines": loglines}


def _fetch_teleport_events(token, org_uuid, session_id):
    """Fetch transcript entries via GET /v1/code/sessions/{id}/teleport-events.

    This is the CCR v2 endpoint that replaced session_ingress.
    Returns a list of logline dicts, or None if the endpoint is unavailable.
    """
    headers = get_api_headers(token, org_uuid)
    headers["anthropic-beta"] = "ccr-byoc-2025-07-29"
    base_url = f"{API_BASE_URL}/code/sessions/{session_id}/teleport-events"

    all_entries = []
    cursor = None
    max_pages = 100

    for page in range(max_pages):
        params = {"limit": 1000}
        if cursor is not None:
            params["cursor"] = cursor

        response = httpx.get(
            base_url,
            headers=headers,
            params=params,
            timeout=30.0,
        )

        if response.status_code == 404:
            # Endpoint not available or session not found — signal fallback
            if page == 0:
                return None
            else:
                # Mid-pagination 404 means session deleted between pages
                return all_entries

        response.raise_for_status()
        data = response.json()

        events = data.get("data", [])
        for ev in events:
            payload = ev.get("payload")
            if payload is not None:
                all_entries.append(payload)

        next_cursor = data.get("next_cursor")
        if next_cursor is None:
            break
        cursor = next_cursor

    return all_entries


def format_session_for_display(session_data):
    """Format a session for display in the list or picker.

    Shows repo first (if available), then date, then title.
    Returns a formatted string.
    """
    title = session_data.get("title", "Untitled")
    created_at = session_data.get("created_at", "")
    repo = session_data.get("repo")
    # Truncate title if too long
    if len(title) > 50:
        title = title[:47] + "..."
    # Format: repo (or placeholder)  date  title
    repo_display = repo if repo else "(no repo)"
    date_display = created_at[:19] if created_at else "N/A"
    return f"{repo_display:30}  {date_display:19}  {title}"
