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


@pytest_asyncio.fixture(scope="function")
async def server_tools():
    """The server module, with its cached client scoped to this test.

    ``server`` memoizes one client process-wide, but pytest-asyncio gives each
    test a fresh event loop -- so a client leaked from an earlier test is bound
    to a closed loop. Reset the cache around every test that calls a tool.
    """
    import codingame_mcp.server as server

    server._client = None
    try:
        yield server
    finally:
        if server._client is not None:
            await server._client.aclose()
            server._client = None
