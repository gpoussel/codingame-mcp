"""Auth/session smoke tests against the live CodinGame API."""

from __future__ import annotations

import pytest

from codingame_mcp import endpoints
from codingame_mcp.client import CodinGameError


async def test_login_verify_returns_user(me):
    """A valid cookie resolves to a codingamer with a numeric user id."""
    assert me.userId is not None
    assert isinstance(me.userId, int)


async def test_session_endpoint_shape(client):
    """Session/findSession still returns a dict carrying the logged-in user."""
    session = await client.request(*endpoints.SESSION_FIND)
    assert isinstance(session, dict)
    assert session.get("codinGamer") or session.get("codingamer")


async def test_error_envelope_raises(client):
    """A bad service path raises CodinGameError (guards the error envelope check)."""
    with pytest.raises(CodinGameError):
        await client.request("CodinGamer", "thisServiceDoesNotExist", [])
