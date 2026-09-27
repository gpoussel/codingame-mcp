"""Tests for the multiplayer (arena) tools.

The live tests read the authenticated user's standing on a multi puzzle. The
play test replays the user's *own* current draft, so the draft it re-saves is
unchanged; it is skipped when the user has no draft for the puzzle.
"""

from __future__ import annotations

import json

import pytest

from codingame_mcp.models import ArenaBattle
from codingame_mcp.server import (
    _battle_row,
    _league,
    _load_code,
    _outcome,
    _placements,
)

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


def test_placements_read_ranks_as_seats_in_finishing_order():
    # Seat 1 won, seat 3 second, seat 2 third, seat 0 last (a Tron game).
    assert _placements([1, 3, 2, 0], [70, 100, 80, 90]) == [3, 0, 2, 1]
    # A drawn 2-player game still lists both seats: equal scores tie them.
    assert _placements([0, 1], [4, 4]) == [0, 0]
    # Ties further down (Code of Kutulu): seats 1 and 2 share third place.
    assert _placements([0, 3, 1, 2], [222, 169, 169, 202]) == [0, 2, 2, 1]
    # Not a permutation: already per-seat places.
    assert _placements([0, 0], [1, 1]) == [0, 0]


def test_outcome_from_placements():
    assert _outcome(_placements([1, 0], [1, 2]), 1) == "win"
    assert _outcome(_placements([0, 1], [4, 4]), 1) == "draw"


def test_battle_row_uses_position_as_the_finishing_place():
    battle = ArenaBattle.model_validate(
        {
            "gameId": 1,
            "done": True,
            "players": [
                {"playerAgentId": 10, "nickname": "a", "position": 1},
                {"playerAgentId": 20, "nickname": "b", "position": 0},
            ],
        }
    )
    row = _battle_row(battle, lambda p: p["playerAgentId"] == 10, None)
    assert row["outcome"] == "loss" and row["place"] == 1
    assert [p["pseudo"] for p in row["players"]] == ["b", "a"]
    assert "seat" not in row


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
    # Below the top league the boss leads the list and is a playable agent
    # (the top league, Legend, has no boss).
    league = session.arena["league"]
    if league["divisionIndex"] < league["divisionCount"] - 1:
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
    if status["league"]["name"] != "Legend":
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


# -- scouting other players ------------------------------------------------


async def test_arena_leaderboard_carries_agents_and_leagues(client):
    puzzle = await client.get_puzzle(ARENA)
    board = await client.get_puzzle_leaderboard(puzzle.puzzleLeaderboardId or ARENA)
    assert board.users and board.leagues
    top = board.users[0]
    assert top.agentId and top.league and "divisionIndex" in top.league
    assert all("divisionAgentsCount" in league for league in board.leagues.values())


async def test_agent_battles_and_their_replay(client):
    puzzle = await client.get_puzzle(ARENA)
    board = await client.get_puzzle_leaderboard(puzzle.puzzleLeaderboardId or ARENA)
    agent = board.users[0].agentId
    battles = await client.get_agent_battles(agent)
    done = [b for b in battles if b.done]
    assert done, "expected finished battles for the top agent"
    players = done[0].players
    assert any(p["playerAgentId"] == agent for p in players)
    assert all(isinstance(p.get("position"), int) and p.get("nickname") for p in players)
    replay = await client.get_game_result(done[0].gameId)
    # Seats come from the replay's agents; ranks lists every seat once.
    assert {a["agentId"] for a in replay.agents} == {p["playerAgentId"] for p in players}
    assert sorted(replay.ranks) == list(range(len(players)))
    assert len(replay.scores) == len(players)


async def test_player_battles_tool_shape(server_tools):
    top = (await server_tools.get_puzzle_leaderboard(ARENA, limit=1))["entries"][0]
    page = await server_tools.get_player_battles(ARENA, pseudo=top["pseudo"], limit=3)
    assert page["player"]["agentId"] == top["agentId"]
    assert page["total"] and len(page["battles"]) <= 3
    battle = page["battles"][0]
    assert battle["outcome"] in ("win", "loss", "draw")
    replay = await server_tools.get_game_replay(
        battle["gameId"], player=top["pseudo"], limit=5
    )
    me = next(a for a in replay["agents"] if a["pseudo"] == top["pseudo"])
    assert me["place"] == battle["place"]
    assert all(f["seat"] == me["seat"] for f in replay["frames"])


async def test_download_game_replays(server_tools, tmp_path):
    top = (await server_tools.get_puzzle_leaderboard(ARENA, limit=1))["entries"][0]
    battles = await server_tools.get_player_battles(ARENA, agent_id=top["agentId"], limit=2)
    ids = [b["gameId"] for b in battles["battles"]]
    saved = await server_tools.download_game_replays(ids, str(tmp_path))
    assert saved["saved"] == len(ids)
    for file in saved["files"]:
        data = json.loads(open(file["path"]).read())
        assert data["frames"] and data["agents"] and data["refereeInput"]
    again = await server_tools.download_game_replays(ids, str(tmp_path))
    assert again["skipped"] == len(ids)
