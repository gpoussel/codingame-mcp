"""Live tests for puzzle listing and detail."""

from __future__ import annotations

import json

import pytest


async def test_list_puzzles_non_empty(client):
    """The authenticated user's puzzle list is non-empty and well-shaped."""
    puzzles = await client.list_puzzles()
    assert puzzles, "expected at least one puzzle"
    first = puzzles[0]
    assert first.id is not None
    assert first.prettyId, "puzzle is missing prettyId"


async def test_list_puzzles_carries_validator_score(client):
    """List entries carry the user's progress, not just the puzzle identity.

    validatorScore is the only progress signal the list endpoint fills in
    (submitted is null on every entry), so list_puzzles is unusable as a
    solved/unsolved overview without it.
    """
    puzzles = await client.list_puzzles()
    assert puzzles, "expected at least one puzzle"
    scores = [p.validatorScore for p in puzzles]
    assert all(s is not None for s in scores), "list entries are missing validatorScore"
    assert all(0 <= s <= 100 for s in scores), "validatorScore is not a percentage"


async def test_list_puzzles_tool_reports_solved(server_tools):
    """The list_puzzles tool surfaces validatorScore plus a derived solved flag."""
    page = await server_tools.list_puzzles()
    entries = page["puzzles"]
    assert entries, "expected at least one puzzle"
    assert all("validatorScore" in e for e in entries)
    assert all(e["solved"] == (e["validatorScore"] == 100) for e in entries)


async def test_list_puzzles_tool_page_fits_in_token_budget(server_tools):
    """A default page stays far below the per-tool token ceiling.

    The whole point of the paging/projection work: the unfiltered listing used
    to serialize to ~800k characters, which no tool call can return.
    """
    page = await server_tools.list_puzzles()
    assert len(page["puzzles"]) == 50
    assert page["total"] > 50, "total must count all matches, not just this page"
    assert len(json.dumps(page)) < 50_000


async def test_list_puzzles_tool_filters_and_pages(server_tools):
    """Filters narrow the total; offset walks the same ordering without overlap."""
    everything = await server_tools.list_puzzles(limit=0)
    easy = await server_tools.list_puzzles(level="easy", limit=0)
    solved_easy = await server_tools.list_puzzles(level="easy", solved=True, limit=0)
    assert 0 < easy["total"] < everything["total"]
    assert solved_easy["total"] <= easy["total"]
    assert not easy["puzzles"], "limit=0 returns counts only"

    first = await server_tools.list_puzzles(level="easy", limit=2)
    second = await server_tools.list_puzzles(level="easy", limit=2, offset=2)
    assert all(e["level"] == "easy" for e in first["puzzles"] + second["puzzles"])
    ids = [e["id"] for e in first["puzzles"]] + [e["id"] for e in second["puzzles"]]
    assert len(set(ids)) == 4, "pages overlap"

    only_solved = await server_tools.list_puzzles(solved=True, limit=5)
    assert all(e["solved"] for e in only_solved["puzzles"])


async def test_list_puzzles_tool_projects_fields(server_tools):
    """fields overrides the default overview, in both directions."""
    page = await server_tools.list_puzzles(limit=3, fields=["prettyId", "topics"])
    assert page["puzzles"], "expected at least one puzzle"
    for entry in page["puzzles"]:
        assert set(entry) <= {"prettyId", "topics"}
        assert "title" not in entry, "default overview fields leaked past the projection"


async def test_get_puzzle_tool_projects_fields(server_tools):
    """get_puzzle can drop the statement, which is the bulk of its payload."""
    full = await server_tools.get_puzzle("the-descent")
    slim = await server_tools.get_puzzle("the-descent", fields=["prettyId", "validatorScore"])
    assert full["statement"], "expected a statement on the full record"
    assert set(slim) == {"prettyId", "validatorScore"}


async def test_get_user_progress_tool_drops_rank_history(server_tools):
    """rank_history is ~99% of the payload and must be opt-in."""
    me = await server_tools.whoami()
    default = await server_tools.get_user_progress(me["publicHandle"])
    assert "rankHistory" not in default["codingamePointsRankingDto"]
    assert len(json.dumps(default)) < 50_000

    full = await server_tools.get_user_progress(me["publicHandle"], include_rank_history=True)
    assert full["codingamePointsRankingDto"]["rankHistory"]


async def test_get_puzzle_by_pretty_id(client):
    """Fetching a single puzzle by pretty id round-trips with the list."""
    puzzles = await client.list_puzzles()
    sample = next((p for p in puzzles if p.prettyId), None)
    if sample is None:
        pytest.skip("no puzzle with a prettyId available")
    puzzle = await client.get_puzzle(sample.prettyId)
    assert puzzle.prettyId == sample.prettyId
    # The single-puzzle endpoint carries the detail fields the list lacks.
    assert puzzle.statement, "puzzle detail is missing its statement"


async def test_get_puzzle_tests_exposes_solving_material(client):
    """A test session yields languages, a stub, and test cases with inlined I/O."""
    puzzles = await client.list_puzzles()
    sample = next((p for p in puzzles if p.prettyId), None)
    if sample is None:
        pytest.skip("no puzzle with a prettyId available")
    tests = await client.get_puzzle_tests(sample.prettyId)
    assert tests.availableLanguages, "expected at least one available language"
    assert tests.testCases, "expected at least one test case"
    first = tests.testCases[0]
    assert first.inputBinaryId is not None
    assert first.testIn is not None, "test case input was not inlined"


async def test_recommend_next_puzzles_shape(client):
    """The recommendation endpoint returns a (possibly empty) list of puzzles."""
    puzzles = await client.list_puzzles()
    sample = next((p for p in puzzles if p.prettyId), None)
    if sample is None:
        pytest.skip("no puzzle with a prettyId available")
    nxt = await client.recommend_next_puzzles(sample.prettyId)
    assert isinstance(nxt, list)
    assert all(p.id is not None for p in nxt)


async def test_account_summary_shape(client):
    """The account summary bundles the navbar counters."""
    summary = await client.get_account_summary()
    assert set(summary) >= {
        "unseenNotifications",
        "lootableQuestCount",
        "newContributionCount",
        "newFeaturedEventCount",
    }
    assert isinstance(summary["unseenNotifications"], list)
