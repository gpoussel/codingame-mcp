"""Live test fixtures.

These tests run against the real CodinGame API to catch breaking changes on
their side. They all require a valid ``rememberMe`` cookie: if
``CODINGAME_REMEMBER_ME`` is unset the whole suite is skipped.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from codingame_mcp.client import CodinGameClient
from codingame_mcp.config import ENV_REMEMBER_ME


def _cookie_missing() -> bool:
    return not os.environ.get(ENV_REMEMBER_ME, "").strip()


def pytest_collection_modifyitems(config, items):
    """Skip the entire (live) suite when no rememberMe cookie is available."""
    if not _cookie_missing():
        return
    skip = pytest.mark.skip(
        reason=f"{ENV_REMEMBER_ME} not set; skipping live CodinGame tests."
    )
    for item in items:
        item.add_marker(skip)


@pytest_asyncio.fixture(scope="function")
async def client():
    """An authenticated client, closed after each test."""
    c = CodinGameClient(os.environ[ENV_REMEMBER_ME].strip())
    try:
        yield c
    finally:
        await c.aclose()


@pytest_asyncio.fixture(scope="function")
async def me(client):
    """The authenticated codingamer (also asserts the cookie is valid)."""
    return await client.login_verify()
