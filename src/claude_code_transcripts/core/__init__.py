"""Stdlib-only core layer.

Every module under ``core`` must import ZERO third-party packages, so the
session-end ``hook`` hot path (and the plugin that will eventually call it) can
import naming/resolution/idempotency logic without pulling in jinja2, markdown,
httpx, click, or questionary. The ``render``, ``fetch``, and ``cli`` layers may
import from here; nothing here may import upward.
"""
