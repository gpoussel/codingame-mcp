"""Configuration for the CodinGame MCP server.

The only secret we need is the ``rememberMe`` cookie value, supplied via the
``CODINGAME_REMEMBER_ME`` environment variable. It is never accepted as a tool
argument so it cannot leak into tool-call transcripts.
"""

from __future__ import annotations

import os

ENV_REMEMBER_ME = "CODINGAME_REMEMBER_ME"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


def get_remember_me_cookie() -> str:
    """Return the CodinGame ``rememberMe`` cookie value from the environment.

    Raises:
        ConfigError: if the environment variable is unset or empty, with an
            actionable message so the server fails fast.
    """
    value = os.environ.get(ENV_REMEMBER_ME, "").strip()
    if not value:
        raise ConfigError(
            f"Environment variable {ENV_REMEMBER_ME!r} is not set. "
            "Set it to the value of the 'rememberMe' cookie from a logged-in "
            "codingame.com browser session (see .env.example)."
        )
    return value
