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

# Fields kept on a list_puzzles entry, by default. An allowlist rather than a
# denylist: the models are extra="allow", so CodinGame can (and does) add heavy
# fields -- topics alone is ~44% of the raw list payload -- and a denylist would
# silently let each new one back into a response that is already near the tool
# token ceiling. Anything omitted here is still reachable via `fields`.
_LIST_PUZZLE_FIELDS = (
    "id",
    "prettyId",
    "title",
    "level",
    "type",
    # submitted is null on every entry and the achievement counts are 0 on all
    # community puzzles, so validatorScore is the only usable progress signal.
    "validatorScore",
    "solved",
    "solvedCount",
    "attemptCount",
)

# rankHistory is ~99% of the get_user_progress payload (1876 datapoints) and
# says nothing about progress, so it is opt-in.
_RANK_HISTORY_FIELD = "rankHistory"

# The two heavyweights of a puzzle record, both opt-in:
# - viewer is the puzzle's *game viewer*, a minified JS bundle. Only multi /
#   optim / some CODE puzzles carry one, but there it dwarfs everything else
#   (up to 240k chars of the 251k payload) and is useless to an agent.
# - statement is the HTML brief: useful, but the single biggest field otherwise,
#   and get_puzzle_tests already returns it alongside the material to solve.
_PUZZLE_VIEWER_FIELD = "viewer"
_PUZZLE_STATEMENT_FIELD = "statement"

# A full listing blows the per-tool token ceiling (1067 puzzles), so paginate.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _project(data: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """Restrict a record to the requested fields (all of them when None)."""
    if not fields:
        return data
    return {key: data[key] for key in fields if key in data}


def _summarize_progress(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce a points-stats record to the handful of fields that mean anything.

    The raw record is dominated by rankHistory and xpThresholds; the actual
    progress -- total points, rank, and the per-category breakdown -- is what
    this keeps.
    """
    gamer = data.get("codingamer") or {}
    ranking = data.get("codingamePointsRankingDto") or {}
    return {
        "pseudo": gamer.get("pseudo"),
        "publicHandle": gamer.get("publicHandle"),
        "level": gamer.get("level"),
        "xp": gamer.get("xp"),
        "rank": gamer.get("rank"),
        "achievementCount": data.get("achievementCount"),
        "codingamePointsTotal": ranking.get("codingamePointsTotal"),
        "codingamePointsRank": ranking.get("codingamePointsRank"),
        "numberCodingamersGlobal": ranking.get("numberCodingamersGlobal"),
        "points": {
            key.removeprefix("codingamePoints")[0].lower()
            + key.removeprefix("codingamePoints")[1:]: value
            for key, value in ranking.items()
            if key.startswith("codingamePoints")
            and key not in ("codingamePointsTotal", "codingamePointsRank")
        },
    }


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
async def get_user_progress(
    handle: str,
    summary: bool = True,
    fields: list[str] | None = None,
    include_rank_history: bool = False,
) -> dict[str, Any]:
    """Get a CodinGame user's points and progress stats by public handle.

    By default returns a summary: total points, rank, and the per-category
    points breakdown. The raw record is ~357k characters, ~99% of it the
    rankHistory timeseries plus xpThresholds, none of which says anything about
    the user's progress.

    Args:
        handle: The user's public handle.
        summary: Return the compact summary (default). Pass false for the raw
            record, which is large.
        fields: Fields to keep, applied to whichever shape you asked for.
        include_rank_history: Include the full rank-history timeseries in the
            raw record. It alone will likely blow the token ceiling. Ignored
            when summary is true.
    """
    client = await get_client()
    stats = await client.get_points_stats(handle)
    data = stats.model_dump()
    if summary:
        return _project(_summarize_progress(data), fields)
    ranking = data.get("codingamePointsRankingDto")
    if not include_rank_history and isinstance(ranking, dict):
        ranking.pop(_RANK_HISTORY_FIELD, None)
    return _project(data, fields)


@mcp.tool()
async def list_puzzles(
    level: str | None = None,
    type: str | None = None,
    solved: bool | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """List puzzles with the authenticated user's progress, filtered and paged.

    Progress is carried by validatorScore (percentage of validators passed, 0
    to 100) and the derived solved flag (validatorScore == 100). Each entry is
    a compact overview; call get_puzzle for the full record.

    The returned total counts every puzzle matching the filters, not just the
    ones on this page -- so a solved/unsolved tally needs no paging through the
    results (e.g. solved=true, limit=0 returns the count alone).

    Args:
        level: Keep only this difficulty ("easy", "medium", "hard", "expert",
            "multi", "optim", "tutorial", "codegolf-*").
        type: Keep only this puzzle type ("CODE", "ARENA", "SOLO", "GOLF",
            "BOT_PROGRAMMING").
        solved: Keep only solved (true) or unsolved (false) puzzles.
        limit: Max entries on this page (0 to _MAX_LIMIT; 0 returns counts only).
        offset: Entries to skip, for paging.
        fields: Fields to keep per entry, overriding the default overview. Any
            field of the underlying record is available (e.g. "topics",
            "lastActivity", "testSessionHandle"), at its full token cost.
    """
    if limit < 0 or limit > _MAX_LIMIT:
        raise ValueError(f"limit must be between 0 and {_MAX_LIMIT}, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")

    client = await get_client()
    puzzles = await client.list_puzzles()

    matched = []
    for puzzle in puzzles:
        data = puzzle.model_dump()
        data["solved"] = puzzle.validatorScore == 100
        if level is not None and data.get("level") != level:
            continue
        if type is not None and data.get("type") != type:
            continue
        if solved is not None and data["solved"] != solved:
            continue
        matched.append(data)

    page = matched[offset : offset + limit]
    keep = list(fields) if fields else list(_LIST_PUZZLE_FIELDS)
    return {
        "total": len(matched),
        "offset": offset,
        "limit": limit,
        "puzzles": [_project(data, keep) for data in page],
    }


@mcp.tool()
async def get_puzzle(
    pretty_id: str,
    include_statement: bool = False,
    include_viewer: bool = False,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Get a single puzzle's metadata plus the authenticated user's progress.

    Returns topics, xp, type, contributor and progress. The two heavy fields are
    opt-in: the statement (HTML brief) and the viewer (a minified JS game bundle
    of up to 240k characters, on multi/optim puzzles). To actually solve a
    puzzle, prefer get_puzzle_tests, which returns the statement together with
    the languages, code stub, and test cases.

    Args:
        pretty_id: The puzzle's pretty id (the slug in its training URL).
        include_statement: Include the HTML statement.
        include_viewer: Include the puzzle's game-viewer JS bundle. Rarely of
            any use to an agent, and large enough to blow the token ceiling.
        fields: Fields to keep. Applied after the two flags above, so it cannot
            resurrect an excluded field.
    """
    client = await get_client()
    puzzle = await client.get_puzzle(pretty_id)
    data = puzzle.model_dump()
    if not include_viewer:
        data.pop(_PUZZLE_VIEWER_FIELD, None)
    if not include_statement:
        data.pop(_PUZZLE_STATEMENT_FIELD, None)
    return _project(data, fields)


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

    @mcp.tool()
    async def claim_puzzle_labels(pretty_id: str) -> dict[str, Any]:
        """Claim a puzzle's labels (topics) onto your profile.

        Marks every not-yet-claimed leaf label of the puzzle as learned (one
        CodinGame call each). **Changes your profile.** Returns the labels that
        were claimed (empty if there was nothing left to claim).

        Args:
            pretty_id: The puzzle's pretty id (the slug in its training URL).
        """
        client = await get_client()
        claimed = await client.claim_puzzle_labels(pretty_id)
        return {
            "claimed": [
                {"id": t.id, "handle": t.handle, "value": t.value} for t in claimed
            ],
            "count": len(claimed),
        }


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
