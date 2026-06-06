"""Live tests for user details and progress.

Uses the authenticated user's own handle so we never hardcode someone else's
account, and asserts on structural invariants (field presence/type) rather than
volatile values like XP or rank.
"""

from __future__ import annotations


async def test_get_points_stats_by_own_handle(client, me):
    """Fetching points stats by the authed user's handle returns their codingamer."""
    assert me.publicHandle, "authenticated user is missing a public handle"
    stats = await client.get_points_stats(me.publicHandle)
    assert stats.codingamer is not None
    assert stats.codingamer.userId == me.userId


async def test_points_stats_exposes_ranking(client, me):
    """The points-stats payload still carries the ranking breakdown we depend on."""
    stats = await client.get_points_stats(me.publicHandle)
    assert stats.codingamePointsRankingDto is not None
    assert isinstance(stats.codingamePointsRankingDto, dict)


async def test_public_info_by_id(client, me):
    """Public info by numeric id matches the authenticated user."""
    info = await client.get_public_info(me.userId)
    assert info.userId == me.userId
