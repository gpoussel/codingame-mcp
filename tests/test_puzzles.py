"""Live tests for puzzle listing and detail."""

from __future__ import annotations

import pytest


async def test_list_puzzles_non_empty(client):
    """The authenticated user's puzzle list is non-empty and well-shaped."""
    puzzles = await client.list_puzzles()
    assert puzzles, "expected at least one puzzle"
    first = puzzles[0]
    assert first.id is not None
    assert first.prettyId, "puzzle is missing prettyId"


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
