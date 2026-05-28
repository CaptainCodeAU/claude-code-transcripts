"""Lazy Jinja2 environment for the render layer.

The environment and macros are built on first use so importing render submodules
(or the package) never forces a Jinja2 import unless rendering actually happens.
"""

import base64
from functools import lru_cache

from jinja2 import Environment, PackageLoader


def _b64encode_filter(value):
    """Base64-encode a value (str or bytes) for use in HTML data attributes."""
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return base64.b64encode(value).decode("ascii")


@lru_cache(maxsize=1)
def get_jinja_env():
    env = Environment(
        loader=PackageLoader("claude_code_transcripts", "templates"),
        autoescape=True,
    )
    env.filters["b64encode"] = _b64encode_filter
    return env


@lru_cache(maxsize=1)
def get_macros():
    """Return the compiled macros module (cached)."""
    return get_jinja_env().get_template("macros.html").module


def get_template(name):
    """Get a Jinja2 template by name."""
    return get_jinja_env().get_template(name)
