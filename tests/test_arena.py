"""Tests for the multiplayer (arena) tools.

The live tests read the authenticated user's standing on a multi puzzle. The
play test replays the user's *own* current draft, so the draft it re-saves is
unchanged; it is skipped when the user has no draft for the puzzle.
"""

from __future__ import annotations

import pytest

from codingame_mcp.server import _league, _load_code, _outcome

# A two-player multi puzzle with a fast referee.
ARENA = "tic-tac-toe"


# -- pure helpers ----------------------------------------------------------


def test_outcome_two_players():
    assert _outcome([0, 1], 0) == "win"
    assert _outcome([0, 1], 1) == "loss"
    assert _outcome([0, 0], 1) == "draw"


def test_outcome_shared_first_place_is_a_draw():
    assert _outcome([0, 0, 2], 1) == "draw"
    assert _outcome([0, 0, 2], 2) == "loss"


def test_league_is_named_from_the_top():
    assert _league({"divisionIndex": 4, "divisionCount": 5})["name"] == "Legend"
    assert _league({"divisionIndex": 2, "divisionCount": 5})["name"] == "Silver"
    assert _league({"divisionIndex": 0, "divisionCount": 7})["name"] == "Wood 3"
    assert _league({"divisionIndex": 0, "divisionCount": 10})["name"] == "Wood 6"
    # Few-league community games start high.
    assert _league({"divisionIndex": 0, "divisionCount": 2})["name"] == "Gold"
    assert _league({"divisionIndex": 0, "divisionCount": 1})["name"] == "Legend"


def test_load_code_reads_file_and_infers_language(tmp_path):
    source = tmp_path / "bot.ts"
    source.write_text("console.log(1)")
    assert _load_code(None, str(source), None) == ("console.log(1)", "TypeScript")
    # An explicit language wins over the extension.
    assert _load_code(None, str(source), "Javascript")[1] == "Javascript"


def test_load_code_requires_exactly_one_source():
    with pytest.raises(ValueError):
        _load_code(None, None, "Python3")
    with pytest.raises(ValueError):
        _load_code("x", "/tmp/x.py", None)
    with pytest.raises(ValueError):
        _load_code("x", None, None)


# -- live ------------------------------------------------------------------


async def test_arena_session_carries_league_and_seats(client):
    session = await client.get_arena_session(ARENA)
    assert session.handle
    placement = session.arena["arenaCodinGamer"]
    assert isinstance(placement["divisionId"], int)
    assert "league" in session.arena
    assert isinstance(session.question.get("nbPlayersMin"), int)


async def test_arena_ranking_and_room_leaderboard(client):
    session = await client.get_arena_session(ARENA)
    ranking = await client.get_arena_ranking(session.handle)
    assert ranking.percentage is not None
    placement = session.arena["arenaCodinGamer"]
    room = await client.get_arena_room_leaderboard(
        placement["divisionId"], placement["roomIndex"]
    )
    assert room.users, "expected a non-empty league room"
    # The boss leads the list and is a playable agent.
    assert any(u.arenaboss and u.agentId for u in room.users)


async def test_last_battles_and_replay(client):
    session = await client.get_arena_session(ARENA)
    battles = await client.get_last_battles(session.handle)
    done = [b for b in battles if b.done]
    if not done:
        pytest.skip("no finished arena battle for this user")
    assert done[0].players and "playerAgentId" in done[0].players[0]
    replay = await client.get_game_result(done[0].gameId)
    assert replay.ranks and replay.frames
    assert replay.refereeInput


async def test_arena_status_tool_shape(server_tools):
    status = await server_tools.get_arena_status(ARENA, neighbours=1)
    assert status["league"]["name"]
    assert status["boss"]["agentId"]
    assert status["players"]["min"] >= 2


async def test_play_game_returns_ranks(client):
    session = await client.get_arena_session(ARENA)
    answer = session.answer or {}
    if not answer.get("code"):
        pytest.skip("no draft to replay for this user")
    low = session.question["nbPlayersMin"]
    result = await client.play_game(
        session.handle,
        answer["programmingLanguageId"],
        answer["code"],
        [-1] + [-2] * (low - 1),
    )
    assert len(result.ranks) == low
    assert result.refereeInput and result.refereeInput.startswith("seed=")
    assert any(f.agentId == 0 for f in result.frames)
