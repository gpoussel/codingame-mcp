"""Live tests for puzzle listing and detail."""

from __future__ import annotations

import pytest

from codingame_mcp.models import PuzzleProgress


async def test_list_puzzles_non_empty(client):
    """The authenticated user's puzzle list is non-empty and well-shaped."""
    puzzles = await client.list_puzzles()
    assert puzzles, "expected at least one puzzle"
    first = puzzles[0]
    assert first.id is not None
    assert first.prettyId, "puzzle is missing prettyId"


async def test_list_puzzles_progress_signals(client):
    """List entries carry the per-user progress fields the tools derive from.

    Guards the dependency surface: validatorScore (the 0-100 grid signal) and
    type must come back from findProgressByIds, and submitted must be backfilled
    from findAllMinimalProgress (it is None on findProgressByIds alone)."""
    puzzles = await client.list_puzzles()
    assert any(p.validatorScore is not None for p in puzzles), "no validatorScore"
    assert any(p.type for p in puzzles), "no puzzle type came back"
    # submitted is backfilled from the minimal call, so it is a real boolean
    # (never None) for at least the puzzles present in that call.
    assert any(isinstance(p.submitted, bool) for p in puzzles), "submitted not filled"
    # A fully-validated SOLO/CODE puzzle is reported solved.
    solved_solo = next(
        (p for p in puzzles if (p.type or "").upper() in ("SOLO", "CODE")
         and p.validatorScore == 100),
        None,
    )
    if solved_solo is not None:
        assert solved_solo.solved is True
        assert solved_solo.userScore == 100


def test_derived_solved_semantics_by_type():
    """solved/userScore/userRank are derived per puzzle type (pure, no network)."""
    solo_done = PuzzleProgress(type="SOLO", validatorScore=100, rank=0)
    assert solo_done.solved is True
    assert solo_done.userScore == 100
    assert solo_done.userRank is None  # rank not meaningful for SOLO

    solo_started = PuzzleProgress(type="CODE", validatorScore=40)
    assert solo_started.solved is False
    assert solo_started.userScore == 40

    golf = PuzzleProgress(type="GOLF", validatorScore=100, rank=4)
    assert golf.solved is True
    assert golf.userRank == 4  # rank surfaced for ranked types

    multi = PuzzleProgress(type="MULTI", validatorScore=0, rank=12)
    assert multi.solved is True  # ranked -> treated as solved
    assert multi.userRank == 12

    unknown = PuzzleProgress(type=None, validatorScore=None)
    assert unknown.solved is None


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
