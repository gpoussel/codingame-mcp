"""FastMCP server exposing read-only CodinGame tools over stdio.

Authentication uses the ``rememberMe`` cookie from ``CODINGAME_REMEMBER_ME``
(see :mod:`codingame_mcp.config`); no tool accepts the cookie as an argument.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import CodinGameClient
from .config import get_remember_me_cookie

mcp = FastMCP("codingame")

# A single shared client, built lazily on first tool use and reused thereafter.
_client: CodinGameClient | None = None
_client_lock = asyncio.Lock()

# Fields dropped from each list_puzzles entry: either always empty there (the
# detail-only fields), noise for a per-puzzle overview, or raw progress now
# surfaced through the derived userScore/userRank/solved fields. Use get_puzzle
# for the full record.
_LIST_PUZZLE_HIDDEN_FIELDS = (
    "creationTime",
    "rank",
    "validatorScore",
    "communityCreation",
    "xpPoints",
    "forumLink",
    "detailsPageUrl",
    "contributor",
    "feedback",
)


async def get_client() -> CodinGameClient:
    """Return the shared client, constructing and authenticating it once."""
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                client = CodinGameClient(get_remember_me_cookie())
                await client.login_verify()  # fail fast on a bad cookie
                _client = client
    return _client


@mcp.tool()
async def whoami() -> dict[str, Any]:
    """Return the authenticated CodinGame user (verifies the rememberMe cookie)."""
    client = await get_client()
    codingamer = await client.login_verify()
    return codingamer.model_dump()


@mcp.tool()
async def get_user(handle: str) -> dict[str, Any]:
    """Get a CodinGame user's public details by their public handle.

    Args:
        handle: The user's public handle (the long hex id in profile URLs),
            not their display pseudo.
    """
    client = await get_client()
    stats = await client.get_points_stats(handle)
    return (stats.codingamer or stats).model_dump()


@mcp.tool()
async def get_user_progress(handle: str) -> dict[str, Any]:
    """Get a CodinGame user's points and progress stats by public handle.

    Args:
        handle: The user's public handle.
    """
    client = await get_client()
    stats = await client.get_points_stats(handle)
    return stats.model_dump()


@mcp.tool()
async def list_puzzles(
    only_unsolved: bool = False,
    min_score: int | None = None,
    max_score: int | None = None,
    puzzle_type: str | None = None,
    level: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List puzzles with the authenticated user's progress, filtered server-side.

    Each entry carries the derived progress signals userScore (0-100 validator
    score, the value that colours the training grid green), userRank (leaderboard
    rank for ranked types), and solved (per-type: validatorScore==100 for
    SOLO/CODE/GOLF/OPTIM; in-a-league/ranked for MULTI/ARENA). The full list is
    ~1000 puzzles, so prefer filtering over fetching everything; call get_puzzle
    for the full per-puzzle record.

    Args:
        only_unsolved: Keep only puzzles the user has not solved (solved is False
            or unknown). Cheaply answers "what's left to do".
        min_score: Keep puzzles whose userScore is >= this (0-100).
        max_score: Keep puzzles whose userScore is <= this (0-100). Combine with
            min_score to find "started but not finished" (e.g. 1..99).
        puzzle_type: Keep only this type (SOLO, CODE, GOLF, OPTIM, MULTI, ARENA);
            case-insensitive.
        level: Keep only this difficulty level (e.g. easy, medium, hard, expert).
        limit: Max number of entries to return after filtering (None = all).
        offset: Number of filtered entries to skip before applying limit.
    """
    client = await get_client()
    puzzles = await client.list_puzzles()

    wanted_type = puzzle_type.upper() if puzzle_type else None

    def keep(puzzle: Any) -> bool:
        if only_unsolved and puzzle.solved:
            return False
        score = puzzle.userScore
        if min_score is not None and (score is None or score < min_score):
            return False
        if max_score is not None and (score is None or score > max_score):
            return False
        if wanted_type and (puzzle.type or "").upper() != wanted_type:
            return False
        if level and (puzzle.level or "") != level:
            return False
        return True

    filtered = [p for p in puzzles if keep(p)]
    window = filtered[offset:] if limit is None else filtered[offset : offset + limit]

    result = []
    for puzzle in window:
        data = puzzle.model_dump()
        for field in _LIST_PUZZLE_HIDDEN_FIELDS:
            data.pop(field, None)
        result.append(data)
    return result


@mcp.tool()
async def get_puzzle(pretty_id: str) -> dict[str, Any]:
    """Get a single puzzle's detail plus the authenticated user's progress.

    Includes the full statement (HTML), topics, xp, type, and contributor.

    Args:
        pretty_id: The puzzle's pretty id (the slug in its training URL).
    """
    client = await get_client()
    puzzle = await client.get_puzzle(pretty_id)
    return puzzle.model_dump()


@mcp.tool()
async def get_puzzle_tests(pretty_id: str, resolve_io: bool = True) -> dict[str, Any]:
    """Get a puzzle's solving material: statement, languages, stub, test cases.

    Opens a test session and returns everything needed to solve the puzzle.

    Args:
        pretty_id: The puzzle's pretty id (the slug in its training URL).
        resolve_io: When true (default), inline each test case's input/output
            text; set false to return only the binary ids and skip the fetches.
    """
    client = await get_client()
    tests = await client.get_puzzle_tests(pretty_id, resolve_io=resolve_io)
    return tests.model_dump()


@mcp.tool()
async def recommend_next_puzzles(pretty_id: str) -> list[dict[str, Any]]:
    """Get the puzzles CodinGame recommends tackling after the given one.

    May be empty (e.g. when the puzzle is already solved).

    Args:
        pretty_id: The puzzle's pretty id (the slug in its training URL).
    """
    client = await get_client()
    puzzles = await client.recommend_next_puzzles(pretty_id)
    return [p.model_dump() for p in puzzles]


@mcp.tool()
async def get_account_summary() -> dict[str, Any]:
    """Get the authenticated user's account counters.

    Returns unseen notifications plus the lootable-quest, new-contribution, and
    new-featured-event counts shown in the site navbar.
    """
    client = await get_client()
    return await client.get_account_summary()


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
