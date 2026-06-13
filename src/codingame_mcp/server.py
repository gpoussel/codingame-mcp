"""FastMCP server exposing read-only CodinGame tools over stdio.

Authentication uses the ``rememberMe`` cookie from ``CODINGAME_REMEMBER_ME``
(see :mod:`codingame_mcp.config`); no tool accepts the cookie as an argument.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import CodinGameClient
from .config import get_remember_me_cookie, writes_enabled

mcp = FastMCP("codingame")

# A single shared client, built lazily on first tool use and reused thereafter.
_client: CodinGameClient | None = None
_client_lock = asyncio.Lock()

# Fields dropped from each list_puzzles entry: either always empty there (the
# detail-only fields) or noise for a per-puzzle overview. Use get_puzzle for
# the full record.
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
async def list_puzzles() -> list[dict[str, Any]]:
    """List all puzzles together with the authenticated user's progress.

    Returns a trimmed overview per puzzle; call get_puzzle for the full record.
    """
    client = await get_client()
    puzzles = await client.list_puzzles()
    result = []
    for puzzle in puzzles:
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


# --- Write tools ----------------------------------------------------------
# Registered only when CODINGAME_ENABLE_WRITES is truthy, so a read-only
# deployment never exposes (or even advertises) operations that change state.
if writes_enabled():

    @mcp.tool()
    async def run_puzzle_tests(
        pretty_id: str,
        language: str,
        code: str,
        test_indexes: list[int] | None = None,
    ) -> dict[str, Any]:
        """Run a puzzle's visible test cases against your code (no scoring).

        Side-effect-free for your ranking: it only runs the visible tests (it
        does persist the code as your session draft). Returns a pass/total
        summary plus each case's result.

        Args:
            pretty_id: The puzzle's pretty id (the slug in its training URL).
            language: A programmingLanguageId, e.g. ``Python3``, ``TypeScript``,
                ``Java`` (see get_puzzle_tests for the valid ids).
            code: The full source to run.
            test_indexes: 1-based test-case indexes to run; defaults to all.
        """
        client = await get_client()
        results = await client.run_tests(pretty_id, language, code, test_indexes)
        passed = sum(1 for r in results if (r.comparison or {}).get("success"))
        return {
            "passed": passed,
            "total": len(results),
            "results": [r.model_dump() for r in results],
        }

    @mcp.tool()
    async def submit_puzzle_solution(
        pretty_id: str, language: str, code: str
    ) -> dict[str, Any]:
        """Submit a solution for official grading (AFFECTS your score/ranking).

        Unlike run_puzzle_tests this is a real submission: it grades the code
        against the hidden validators and updates your puzzle score. Polls until
        grading finishes, then returns the score and per-validator results.

        Args:
            pretty_id: The puzzle's pretty id (the slug in its training URL).
            language: A programmingLanguageId, e.g. ``Python3``, ``TypeScript``.
            code: The full source to submit.
        """
        client = await get_client()
        report = await client.submit(pretty_id, language, code)
        return {
            "submissionId": report.submissionId,
            "score": report.score,
            "passed": sum(1 for v in report.validators if v.success),
            "total": len(report.validators),
            "validators": [
                {"name": v.name, "success": v.success} for v in report.validators
            ],
        }


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
