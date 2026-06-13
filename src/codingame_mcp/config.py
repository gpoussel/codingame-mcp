"""Configuration for the CodinGame MCP server.

The only secret we need is the ``rememberMe`` cookie value, supplied via the
``CODINGAME_REMEMBER_ME`` environment variable. It is never accepted as a tool
argument so it cannot leak into tool-call transcripts.
"""

from __future__ import annotations

import os

ENV_REMEMBER_ME = "CODINGAME_REMEMBER_ME"
# When truthy, the server also exposes the write tools (run tests / submit).
ENV_ENABLE_WRITES = "CODINGAME_ENABLE_WRITES"

_TRUTHY = {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


def writes_enabled() -> bool:
    """Return whether write tools should be exposed.

    Reads ``CODINGAME_ENABLE_WRITES`` and treats ``1``/``true``/``yes``/``on``
    (case-insensitive, surrounding whitespace ignored) as enabled; everything
    else -- including unset -- keeps the server read-only.
    """
    return os.environ.get(ENV_ENABLE_WRITES, "").strip().lower() in _TRUTHY


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
