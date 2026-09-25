"""Live tests for puzzle leaderboards.

Asserts structural invariants only (fields present, ordering, filter applied),
never who holds which rank.
"""

from __future__ import annotations

import json

# A code-golf puzzle whose leaderboard id differs from its pretty id, so the
# tool's id resolution is exercised too.
PRETTY_ID = "power-of-thor"
LEADERBOARD_ID = "thor-codesize"


async def test_puzzle_exposes_leaderboard_id(client):
    """get_puzzle carries the puzzleLeaderboardId the leaderboard call needs."""
    puzzle = await client.get_puzzle(PRETTY_ID)
    assert puzzle.puzzleLeaderboardId == LEADERBOARD_ID


async def test_leaderboard_entries_are_well_shaped(client):
    """Entries carry the fields the tool relies on, best first."""
    board = await client.get_puzzle_leaderboard(LEADERBOARD_ID)
    assert board.users, "expected a non-empty leaderboard"
    assert board.count and board.filteredCount
    first = board.users[0]
    assert first.pseudo is not None
    assert first.score is not None and first.criteriaScore is not None
    assert first.programmingLanguage and first.creationTime
    assert first.codingamer is not None and first.codingamer.userId is not None
    ranks = [u.rank for u in board.users]
    assert ranks == sorted(ranks), "entries are not ordered by rank"


async def test_leaderboard_language_filter(client):
    """The language filter keeps only that language and shrinks the count."""
    board = await client.get_puzzle_leaderboard(LEADERBOARD_ID, "TypeScript")
    assert board.users, "expected TypeScript entries"
    assert {u.programmingLanguage for u in board.users} == {"TypeScript"}
    assert board.filteredCount < board.count


async def test_leaderboard_tool_ranks_within_filter(server_tools):
    """The tool ranks within the filtered list, pages, and stays compact."""
    page = await server_tools.get_puzzle_leaderboard(PRETTY_ID, "TypeScript", limit=5)
    assert page["leaderboardId"] == LEADERBOARD_ID
    entries = page["entries"]
    assert len(entries) == 5
    assert entries[0]["rank"] == 1
    assert all(e["submittedAt"] for e in entries)
    ranks = [e["rank"] for e in entries]
    assert ranks == sorted(ranks)
    assert len(json.dumps(page)) < 10_000
