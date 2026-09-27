"""MCP server exposing read-only CodinGame tools over stdio.

Authentication uses the ``rememberMe`` cookie from ``CODINGAME_REMEMBER_ME``
(see :mod:`codingame_mcp.config`); no tool accepts the cookie as an argument.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import CodinGameClient
from .models import GameResult
from .config import get_remember_me_cookie, writes_enabled

mcp = MCPServer("codingame")

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


# --- Multiplayer shaping ----------------------------------------------------

# League names by distance from the top league, as the site names them.
# CodinGame only sends indexes (divisionIndex out of divisionCount): the top is
# always Legend, then Gold, Silver, Bronze, and as many Wood leagues as needed
# (Wood 1 just below Bronze). So a 2-league game starts in Gold.
_LEAGUE_NAMES_FROM_TOP = ("Legend", "Gold", "Silver", "Bronze")

# Seat aliases accepted by the play tool, mapped to play's agentsIds.
_SELF_AGENT = -1
_BOSS_AGENT = -2

# Summary/tooltip markup: "¤RED¤$0 timeout!§RED§" colours a span.
_MARKUP = re.compile(r"[¤§][A-Z]+[¤§]")

# Source extension -> programmingLanguageId, so code_file needs no language.
_LANGUAGE_BY_EXTENSION = {
    ".ts": "TypeScript",
    ".js": "Javascript",
    ".py": "Python3",
    ".rs": "Rust",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".cs": "C#",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".scala": "Scala",
    ".swift": "Swift",
    ".hs": "Haskell",
    ".lua": "Lua",
    ".dart": "Dart",
    ".ml": "OCaml",
    ".fs": "F#",
    ".sh": "Bash",
}

_MAX_GAMES = 20
_MAX_FRAMES = 400


def _load_code(
    code: str | None, code_file: str | None, language: str | None
) -> tuple[str, str]:
    """Resolve the (code, language) pair of a write tool.

    Exactly one of ``code``/``code_file`` is required. Reading a local file
    spares the caller from pasting a whole bot into the tool call; its
    extension then gives the language when none is passed.
    """
    if (code is None) == (code_file is None):
        raise ValueError("pass exactly one of code or code_file")
    if code_file is not None:
        path = Path(code_file).expanduser()
        if not path.is_absolute():
            raise ValueError(f"code_file must be an absolute path, got {code_file!r}")
        code = path.read_text(encoding="utf-8")
        language = language or _LANGUAGE_BY_EXTENSION.get(path.suffix.lower())
    if not language:
        raise ValueError("language is required (could not infer it from code_file)")
    assert code is not None
    return code, language


def _league(league: dict[str, Any] | None) -> dict[str, Any] | None:
    """Name a league from its index, keeping the raw index/count."""
    if not league:
        return None
    index, count = league.get("divisionIndex"), league.get("divisionCount")
    name = None
    if isinstance(index, int) and isinstance(count, int):
        from_top = count - 1 - index
        if 0 <= from_top < len(_LEAGUE_NAMES_FROM_TOP):
            name = _LEAGUE_NAMES_FROM_TOP[from_top]
        elif from_top >= len(_LEAGUE_NAMES_FROM_TOP):
            name = f"Wood {from_top - len(_LEAGUE_NAMES_FROM_TOP) + 1}"
    return {"name": name, "index": index, "count": count}


def _entry_row(entry: Any) -> dict[str, Any]:
    """Compact a room leaderboard entry (an ArenaRanking)."""
    return {
        "rank": entry.localRank if entry.localRank is not None else entry.rank,
        "pseudo": entry.pseudo,
        "score": entry.score,
        "language": entry.programmingLanguage,
        "agentId": entry.agentId,
    }


def _strip_markup(text: str) -> str:
    return _MARKUP.sub("", text)


def _seed(result: GameResult) -> str | None:
    """The referee input that replays the game (e.g. ``seed=123``)."""
    return (result.refereeInput or "").strip() or None


def _placements(ranks: list[int], scores: list[float]) -> list[int]:
    """Each seat's finishing place (0 = winner, ties share a place).

    A game's ``ranks`` lists the seats in finishing order, without ties
    (``[1, 3, 2, 0]``: seat 1 won, seat 0 came last); seats that follow each
    other with equal scores share a place, as on the battle list (a drawn
    tic-tac-toe game is ranks ``[0, 1]``, scores ``[4, 4]``). A ``ranks`` that
    is not a permutation of the seats is taken as per-seat places already.
    """
    if sorted(ranks) != list(range(len(ranks))):
        return list(ranks)
    places = [0] * len(ranks)
    for position, seat in enumerate(ranks):
        previous = ranks[position - 1] if position else None
        tied = (
            previous is not None
            and seat < len(scores)
            and previous < len(scores)
            and scores[seat] == scores[previous]
        )
        places[seat] = places[previous] if tied else position
    return places


def _outcome(ranks: list[int], seat: int) -> str | None:
    """win/loss/draw for ``seat`` from per-seat places: 0 wins, a shared best
    place draws. Pass a game's :func:`_placements`, not its raw ``ranks``."""
    if seat >= len(ranks):
        return None
    mine = ranks[seat]
    if all(r == mine for r in ranks):
        return "draw"
    if mine == min(ranks):
        return "draw" if ranks.count(mine) > 1 else "win"
    return "loss"


def _events(result: GameResult, names: dict[int, str]) -> list[str]:
    """The game's notable events: tooltips plus coloured (alert) summaries.

    ``$<seat>`` placeholders are replaced by the seat's name (e.g. "me").
    """

    def name(text: str) -> str:
        return re.sub(r"\$(\d+)", lambda m: names.get(int(m.group(1)), m.group(0)), text)

    events: list[str] = []
    for raw in result.tooltips:
        try:
            tip = json.loads(raw)
            events.append(f"turn {tip.get('turn')}: {name(_strip_markup(tip.get('text', '')))}")
        except (ValueError, AttributeError):
            events.append(name(_strip_markup(raw)))
    for index, frame in enumerate(result.frames):
        for line in (frame.summary or "").splitlines():
            if "¤" in line:
                text = name(_strip_markup(line))
                # Timeouts etc. are often a tooltip too: keep one of the two.
                if not any(e.endswith(f": {text}") for e in events):
                    events.append(f"frame {index}: {text}")
    return events


def _stderr_tail(result: GameResult, seat: int, lines: int) -> str | None:
    """The last ``lines`` lines ``seat`` wrote to stderr over the game."""
    if lines <= 0:
        return None
    collected: list[str] = []
    for frame in result.frames:
        if frame.agentId == seat and frame.stderr:
            collected.extend(frame.stderr.splitlines())
    return "\n".join(collected[-lines:]) or None


def _game_summary(
    result: GameResult, seat: int, names: dict[int, str], stderr_tail: int
) -> dict[str, Any]:
    """Shape one game for the LLM: outcome, seed, events, optional stderr."""
    summary = {
        "gameId": result.gameId,
        "seed": _seed(result),
        "seat": seat,
        "players": [names.get(i, f"seat {i}") for i in range(len(result.ranks))],
        "outcome": _outcome(_placements(result.ranks, result.scores), seat),
        "places": _placements(result.ranks, result.scores),
        "scores": result.scores,
        "turns": sum(1 for f in result.frames if f.agentId == seat),
        "events": _events(result, names),
    }
    tail = _stderr_tail(result, seat, stderr_tail)
    if tail is not None:
        summary["stderr"] = tail
    return summary


def _tally(outcomes: list[str | None]) -> dict[str, Any]:
    wins, losses, draws = (outcomes.count(k) for k in ("win", "loss", "draw"))
    played = wins + losses + draws
    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "winRate": round(wins / played, 3) if played else None,
    }


def _battle_row(battle: Any, is_focus: Any, result: GameResult | None) -> dict[str, Any]:
    """Shape one battle from the focus player's point of view.

    The outcome comes from the players' ``position`` (their finishing place),
    so it needs no replay; ``result``, when fetched, adds the focus seat and
    the seed that replays the game.
    """
    players = battle.players
    focus = next((i for i, p in enumerate(players) if is_focus(p)), None)
    places = [p.get("position") for p in players]
    row: dict[str, Any] = {
        "gameId": battle.gameId,
        "done": battle.done,
        "outcome": (
            _outcome(places, focus)
            if battle.done and focus is not None and None not in places
            else None
        ),
        "place": places[focus] if focus is not None else None,
        "players": [
            {
                "pseudo": p.get("nickname"),
                "agentId": p.get("playerAgentId"),
                "place": p.get("position"),
            }
            for p in sorted(players, key=lambda p: p.get("position", 0))
        ],
    }
    if result is not None:
        agent_id = players[focus].get("playerAgentId") if focus is not None else None
        row["seat"] = next(
            (a.get("index") for a in result.agents if a.get("agentId") == agent_id), None
        )
        row["seed"] = _seed(result)
    return row


async def _battle_rows(
    client: CodinGameClient, battles: list[Any], is_focus: Any, with_replays: bool
) -> list[dict[str, Any]]:
    """Shape battles, fetching their replays (5 at a time) when asked."""
    semaphore = asyncio.Semaphore(5)

    async def replay(battle: Any) -> GameResult | None:
        if not with_replays or not battle.done or battle.gameId is None:
            return None
        async with semaphore:
            return await client.get_game_result(battle.gameId)

    results = await asyncio.gather(*(replay(b) for b in battles))
    return [_battle_row(b, is_focus, r) for b, r in zip(battles, results)]


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


def _leaderboard_rows(entries: list[Any]) -> list[dict[str, Any]]:
    """Shape leaderboard entries, ranked within the (possibly filtered) list.

    The API's ``rank`` is the global one, even on a language-filtered board, so
    the in-list rank is recomputed: entries arrive best first, and entries tied
    on (score, criteriaScore) share the rank of the first of them.
    """
    rows: list[dict[str, Any]] = []
    rank = 0
    previous: tuple[Any, Any] | None = None
    for position, entry in enumerate(entries, start=1):
        key = (entry.score, entry.criteriaScore)
        if key != previous:
            rank, previous = position, key
        submitted = (
            datetime.fromtimestamp(entry.creationTime / 1000, tz=timezone.utc)
            .isoformat(timespec="seconds")
            if entry.creationTime
            else None
        )
        rows.append(
            {
                "rank": rank,
                "globalRank": entry.rank,
                "pseudo": entry.pseudo,
                "language": entry.programmingLanguage,
                "score": entry.score,
                "criteriaScore": entry.criteriaScore,
                "submittedAt": submitted,
                "userId": entry.codingamer.userId if entry.codingamer else None,
            }
        )
        if entry.agentId is not None:
            # Multi puzzle: the agent to scout (get_player_battles) or play.
            rows[-1]["league"] = (_league(entry.league) or {}).get("name")
            rows[-1]["agentId"] = entry.agentId
    return rows


@mcp.tool()
async def get_puzzle_leaderboard(
    pretty_id: str,
    language: str | None = None,
    pseudo: str | None = None,
    league: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Get a puzzle's leaderboard (incl. multiplayer arenas), with dates.

    Each entry is one user's best in one language: its rank within this list
    (ties share a rank), the global rank, pseudo, language, score (validator
    % on puzzles, the arena score on multis), criteriaScore (the optimization
    criterion -- bytes on code-golf puzzles) and submittedAt (UTC). On a
    multiplayer puzzle the board spans every league (best first) and each
    entry also has its league and agentId: pass the agentId (or pseudo) to
    get_player_battles to study that player's games, or to play_arena_games
    as an opponent. The authenticated user's own entry is returned as "me"
    when it is on the board, wherever it sits relative to the page.

    CodinGame caps a leaderboard at 1000 entries: "capped" is true when the
    list is truncated (then ranks past the cap and "me" may be missing).
    Filtering keeps the list under the cap; CodinGame filters on one column
    at a time, so pass at most one of language, pseudo and league.

    Args:
        pretty_id: The puzzle's pretty id (the slug in its training URL).
        language: A programmingLanguageId (e.g. ``TypeScript``) to restrict the
            leaderboard to; all languages when omitted.
        pseudo: Keep the players whose pseudo contains this text (any rank,
            even past the 1000-entry cap).
        league: Multi puzzles: keep one league ("Legend", "Gold", "Silver",
            "Bronze", "Wood 1", ...).
        limit: Max entries on this page (0 to _MAX_LIMIT; 0 returns counts and
            "me" only).
        offset: Entries to skip, for paging.
    """
    if limit < 0 or limit > _MAX_LIMIT:
        raise ValueError(f"limit must be between 0 and {_MAX_LIMIT}, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")

    client = await get_client()
    puzzle = await client.get_puzzle(pretty_id)
    leaderboard_id = puzzle.puzzleLeaderboardId or pretty_id
    board = await client.get_puzzle_leaderboard(
        leaderboard_id, language, pseudo=pseudo, league=league
    )
    rows = _leaderboard_rows(board.users)
    user_id = await client.get_user_id()
    me = next((row for row in rows if row["userId"] == user_id), None)
    total = board.filteredCount if board.filteredCount is not None else len(rows)
    return {
        "puzzle": pretty_id,
        "leaderboardId": leaderboard_id,
        "criteria": board.criteria,
        "filter": {"language": language, "pseudo": pseudo, "league": league},
        "total": total,
        "capped": len(rows) < total,
        # Multi puzzles: agents per league, best league first.
        "leagues": {
            (_league(info) or {}).get("name") or index: info.get("divisionAgentsCount")
            for index, info in sorted(
                (board.leagues or {}).items(), key=lambda item: -int(item[0])
            )
        }
        or None,
        "me": me,
        "offset": offset,
        "limit": limit,
        "entries": rows[offset : offset + limit],
    }


@mcp.tool()
async def get_arena_status(pretty_id: str, neighbours: int = 5) -> dict[str, Any]:
    """Get your standing on a multiplayer (bot programming) puzzle.

    Returns your league (named: Wood 3..1, Bronze, Silver, Gold, Legend), rank
    within the league room, score, and whether your last submission is still
    playing its ranking games (``percentage`` < 100 / ``inProgress``). Also
    returns the league boss (beat its score to be promoted, checked every
    ``promotionIntervalSeconds``) and the agents ranked around you: their
    ``agentId`` can be passed to play_arena_games as opponents. For the
    league's rules (statement) and input stub, use get_puzzle_tests.

    Args:
        pretty_id: The multi puzzle's pretty id (e.g. ``mad-pod-racing``).
        neighbours: How many agents above and below you to list (0 to 50).
    """
    if neighbours < 0 or neighbours > 50:
        raise ValueError(f"neighbours must be between 0 and 50, got {neighbours}")
    client = await get_client()
    session = await client.get_arena_session(pretty_id)
    arena = session.arena or {}
    placement = arena.get("arenaCodinGamer") or {}
    division = arena.get("division") or {}
    ranking = await client.get_arena_ranking(session.handle)
    room = await client.get_arena_room_leaderboard(
        placement.get("divisionId"), placement.get("roomIndex") or 0
    )
    boss = next((u for u in room.users if u.arenaboss), None)
    my_rank = ranking.localRank if ranking.localRank is not None else ranking.rank
    around = []
    if my_rank is not None and neighbours:
        # The room list stops at 1000 entries: past the cap, the agents closest
        # to you are the last ones listed, so take the nearest by rank.
        ranked = [u for u in room.users if u.localRank is not None and u.agentId != ranking.agentId]
        ranked.sort(key=lambda u: abs(u.localRank - my_rank))
        around = sorted(
            (_entry_row(u) for u in ranked[: 2 * neighbours]), key=lambda r: r["rank"]
        )
    question = session.question
    return {
        "puzzle": pretty_id,
        "leagueTitle": question.get("title"),
        "league": _league(arena.get("league")),
        "players": {"min": question.get("nbPlayersMin"), "max": question.get("nbPlayersMax")},
        "draftLanguage": (session.answer or {}).get("programmingLanguageId"),
        "hasAgent": session.hasAgent,
        "me": {
            "rank": my_rank,
            "total": ranking.total if ranking.total is not None else room.count,
            "score": ranking.score,
            "agentId": ranking.agentId,
            "language": ranking.programmingLanguage,
            "percentage": ranking.percentage,
            "inProgress": ranking.inProgress,
            "eligibleForPromotion": ranking.eligibleForPromotion,
        }
        if ranking.agentId is not None
        else None,
        "boss": _entry_row(boss) if boss else None,
        "promotionIntervalSeconds": division.get("promotionInterval"),
        "nextPromotionInSeconds": (
            arena["timeToPromotion"] // 1000 if arena.get("timeToPromotion") else None
        ),
        "neighbours": around,
        # Past the room list's 1000-entry cap, "neighbours" are just the last
        # agents listed, all ranked above you.
        "neighboursCapped": bool(
            around and my_rank is not None and my_rank - around[-1]["rank"] > 1
            and all(r["rank"] < my_rank for r in around)
        ),
    }


@mcp.tool()
async def get_arena_battles(
    pretty_id: str, limit: int = 20, include_seeds: bool = True
) -> dict[str, Any]:
    """Get your arena agent's last battles with their outcome.

    Each battle lists the players (pseudo, agentId, finishing place, best
    first), your place and outcome (win/loss/draw), and -- with
    include_seeds -- your seat and the seed. Pass a battle's gameId to
    get_game_replay to see what happened, or its seed to play_arena_games to
    replay it against a new version of your code. To study someone else's
    games, use get_player_battles.

    Args:
        pretty_id: The multi puzzle's pretty id.
        limit: How many of the most recent battles to return (1 to 70).
        include_seeds: Fetch each battle's replay for your seat and the seed
            (slower: one replay per battle).
    """
    if limit < 1 or limit > 70:
        raise ValueError(f"limit must be between 1 and 70, got {limit}")
    client = await get_client()
    user_id = await client.get_user_id()
    handle = (await client.get_arena_session(pretty_id)).handle
    battles = (await client.get_last_battles(handle))[:limit]
    rows = await _battle_rows(
        client, battles, lambda p: p.get("userId") == user_id, include_seeds
    )
    return {**_tally([r["outcome"] for r in rows]), "battles": rows}


async def _find_player(
    client: CodinGameClient, pretty_id: str, pseudo: str
) -> dict[str, Any]:
    """Find a player's leaderboard entry on a multi puzzle by pseudo.

    The leaderboard's pseudo filter matches substrings: an exact
    (case-insensitive) match wins, else the match must be unique.
    """
    puzzle = await client.get_puzzle(pretty_id)
    board = await client.get_puzzle_leaderboard(
        puzzle.puzzleLeaderboardId or pretty_id, pseudo=pseudo
    )
    rows = [r for r in _leaderboard_rows(board.users) if r.get("agentId") is not None]
    exact = [r for r in rows if (r["pseudo"] or "").lower() == pseudo.lower()]
    matches = exact or rows
    if not matches:
        raise ValueError(f"no player matching {pseudo!r} on {pretty_id}'s leaderboard")
    if len(matches) > 1:
        names = ", ".join(r["pseudo"] or "?" for r in matches[:10])
        raise ValueError(f"{pseudo!r} matches several players ({names}): be more precise")
    row = matches[0]
    row["rank"] = row.pop("globalRank")
    return row


@mcp.tool()
async def get_player_battles(
    pretty_id: str,
    pseudo: str | None = None,
    agent_id: int | None = None,
    opponent: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_seeds: bool = False,
) -> dict[str, Any]:
    """Get any player's last arena battles -- e.g. a top player's, to study.

    Identify the player by pseudo (looked up on the puzzle's leaderboard, any
    rank) or by agentId (from get_puzzle_leaderboard / get_arena_status).
    CodinGame keeps an agent's last ~240 battles, most recent first. Each
    battle lists its players (pseudo, agentId, finishing place, best first)
    and the player's place and outcome, with the win/loss/draw tally over the
    returned battles. Then use get_game_replay(gameId, player=<pseudo>) to
    read their moves turn by turn, or download_game_replays to save full
    replays to disk for offline analysis.

    Args:
        pretty_id: The multi puzzle's pretty id (e.g. ``mad-pod-racing``).
        pseudo: The player's pseudo (exact match preferred, case-insensitive).
        agent_id: The player's arena agentId, instead of pseudo.
        opponent: Keep only the battles against a player whose pseudo contains
            this text (case-insensitive).
        limit: Max battles returned (1 to 100).
        offset: Battles to skip (after the opponent filter), for paging.
        include_seeds: Fetch each returned battle's replay for the player's
            seat and the seed, to replay it with play_arena_games (slower).
    """
    if (pseudo is None) == (agent_id is None):
        raise ValueError("pass exactly one of pseudo or agent_id")
    if limit < 1 or limit > 100:
        raise ValueError(f"limit must be between 1 and 100, got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    client = await get_client()
    player = await _find_player(client, pretty_id, pseudo) if pseudo else None
    agent = player["agentId"] if player else agent_id
    battles = await client.get_agent_battles(agent)
    if opponent:
        needle = opponent.lower()
        battles = [
            b
            for b in battles
            if any(
                needle in (p.get("nickname") or "").lower()
                and p.get("playerAgentId") != agent
                for p in b.players
            )
        ]
    page = battles[offset : offset + limit]
    rows = await _battle_rows(
        client, page, lambda p: p.get("playerAgentId") == agent, include_seeds
    )
    if player is None:
        # Name the player from the battles themselves.
        nickname = next(
            (
                p.get("nickname")
                for b in battles
                for p in b.players
                if p.get("playerAgentId") == agent
            ),
            None,
        )
        player = {"pseudo": nickname, "agentId": agent}
    return {
        "player": player,
        "total": len(battles),
        "offset": offset,
        **_tally([r["outcome"] for r in rows]),
        "battles": rows,
    }


def _agent_names(result: GameResult) -> dict[int, str]:
    """Seat -> pseudo (or the boss's nickname) of a replay's agents."""
    return {
        a.get("index"): (a.get("codingamer") or {}).get("pseudo")
        or (a.get("arenaboss") or {}).get("nickname")
        for a in result.agents
    }


@mcp.tool()
async def get_game_replay(
    game_id: int,
    seat: int | None = None,
    player: str | None = None,
    offset: int = 0,
    limit: int = 100,
    include_view: bool = False,
) -> dict[str, Any]:
    """Get a game's turn-by-turn log: each seat's output, stderr and summary.

    Works on any game: your arena battles, games played with
    play_arena_games, and other players' battles (get_player_battles) --
    every seat's stdout (its actions) is visible, but only your own stderr.
    Frame 0 is the initialisation; each later frame belongs to the seat in
    ``seat``. ``agents`` gives each seat's pseudo, agentId and finishing
    place (0 = winner).

    Args:
        game_id: The game id (from get_arena_battles, get_player_battles or
            play_arena_games).
        seat: Keep only this seat's frames (0-based); all seats when omitted.
        player: Keep only this player's frames, by pseudo (instead of seat).
        offset: Frames to skip (after the seat filter), for paging.
        limit: Max frames returned (1 to 400).
        include_view: Include each frame's viewer data -- the game state the
            viewer draws (positions, ...); large, but the only per-turn state.
    """
    if limit < 1 or limit > _MAX_FRAMES:
        raise ValueError(f"limit must be between 1 and {_MAX_FRAMES}, got {limit}")
    if seat is not None and player is not None:
        raise ValueError("pass at most one of seat or player")
    client = await get_client()
    result = await client.get_game_result(game_id)
    names = _agent_names(result)
    if player is not None:
        seat = next(
            (i for i, n in names.items() if (n or "").lower() == player.lower()), None
        )
        if seat is None:
            raise ValueError(
                f"{player!r} is not in game {game_id} (players: "
                f"{', '.join(n or '?' for n in names.values())})"
            )
    frames = [
        {"frame": index, **f.model_dump(exclude_none=True)}
        for index, f in enumerate(result.frames)
        if seat is None or f.agentId == seat
    ]
    for frame in frames:
        frame["seat"] = frame.pop("agentId", None)
        frame.pop("keyframe", None)
        if not include_view:
            frame.pop("view", None)
        for key in [k for k, v in frame.items() if v == ""]:
            del frame[key]
    places = _placements(result.ranks, result.scores)
    return {
        "gameId": result.gameId,
        "seed": _seed(result),
        "agents": [
            {
                "seat": a.get("index"),
                "pseudo": names.get(a.get("index")),
                "agentId": a.get("agentId"),
                "place": places[a["index"]]
                if isinstance(a.get("index"), int) and a["index"] < len(places)
                else None,
                "score": result.scores[a["index"]]
                if isinstance(a.get("index"), int) and a["index"] < len(result.scores)
                else None,
            }
            for a in result.agents
        ],
        "events": _events(result, {k: v for k, v in names.items() if v}),
        "totalFrames": len(frames),
        "offset": offset,
        "frames": frames[offset : offset + limit],
    }


@mcp.tool()
async def download_game_replays(game_ids: list[int], directory: str) -> dict[str, Any]:
    """Save full game replays as JSON files, for offline analysis.

    Writes ``<directory>/<gameId>.json`` per game: the raw replay with every
    frame (stdout, stderr, summary, view -- the per-turn game state), the
    agents (``index`` is the seat), scores and ``refereeInput`` (the seed).
    Note ``ranks`` there lists the *seats in finishing order*, not each
    seat's rank. A replay is ~100-300k chars, too big to read whole in a tool
    call: parse the files with a script instead. Games already saved are
    skipped. Get gameIds from get_player_battles or get_arena_battles.

    Args:
        game_ids: The games to save (1 to 100).
        directory: Absolute path of the directory to write to (created if
            missing).
    """
    if not 1 <= len(game_ids) <= 100:
        raise ValueError(f"pass 1 to 100 game ids, got {len(game_ids)}")
    target = Path(directory).expanduser()
    if not target.is_absolute():
        raise ValueError(f"directory must be an absolute path, got {directory!r}")
    target.mkdir(parents=True, exist_ok=True)
    client = await get_client()
    semaphore = asyncio.Semaphore(5)

    async def save(game_id: int) -> dict[str, Any]:
        path = target / f"{game_id}.json"
        if path.exists():
            return {"gameId": game_id, "path": str(path), "skipped": True}
        try:
            async with semaphore:
                result = await client.get_game_result(game_id)
        except Exception as error:  # keep the other downloads going
            return {"gameId": game_id, "error": str(error)}
        path.write_text(json.dumps(result.model_dump(mode="json")), encoding="utf-8")
        names = _agent_names(result)
        return {
            "gameId": game_id,
            "path": str(path),
            "players": [names.get(i) for i in range(len(result.scores))],
            "frames": len(result.frames),
            "bytes": path.stat().st_size,
        }

    files = await asyncio.gather(*(save(g) for g in dict.fromkeys(game_ids)))
    return {
        "directory": str(target),
        "saved": sum(1 for f in files if "bytes" in f),
        "skipped": sum(1 for f in files if f.get("skipped")),
        "failed": sum(1 for f in files if "error" in f),
        "files": files,
    }


# --- Write tools ----------------------------------------------------------
# Registered only when CODINGAME_ENABLE_WRITES is truthy, so a read-only
# deployment never exposes (or even advertises) operations that change state.
if writes_enabled():

    @mcp.tool()
    async def run_puzzle_tests(
        pretty_id: str,
        language: str | None = None,
        code: str | None = None,
        test_indexes: list[int] | None = None,
        code_file: str | None = None,
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
            code_file: Absolute path of a local source file to run instead of
                ``code``; its extension gives the language when omitted.
        """
        code, language = _load_code(code, code_file, language)
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
        pretty_id: str,
        language: str | None = None,
        code: str | None = None,
        code_file: str | None = None,
    ) -> dict[str, Any]:
        """Submit a solution for official grading (AFFECTS your score/ranking).

        Unlike run_puzzle_tests this is a real submission: it grades the code
        against the hidden validators and updates your puzzle score. Polls until
        grading finishes, then returns the score and per-validator results.

        Args:
            pretty_id: The puzzle's pretty id (the slug in its training URL).
            language: A programmingLanguageId, e.g. ``Python3``, ``TypeScript``.
            code: The full source to submit.
            code_file: Absolute path of a local source file to submit instead
                of ``code``; its extension gives the language when omitted.
        """
        code, language = _load_code(code, code_file, language)
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

    @mcp.tool()
    async def play_arena_games(
        pretty_id: str,
        language: str | None = None,
        code: str | None = None,
        code_file: str | None = None,
        opponents: list[str | int] | None = None,
        games: int = 1,
        seed: str | None = None,
        rotate_seats: bool = True,
        stderr_tail: int = 0,
    ) -> dict[str, Any]:
        """Play games of a multiplayer puzzle in the IDE (no effect on ranking).

        Plays ``games`` games sequentially and returns the win/loss/draw tally
        plus a compact summary per game: outcome, seed, turns, events
        (timeouts, invalid actions, ...), and optionally your stderr tail. Use
        get_game_replay with a gameId for the full turn-by-turn log. Like a
        test run, this saves the code as your draft for the puzzle.

        Args:
            pretty_id: The multi puzzle's pretty id (e.g. ``mad-pod-racing``).
            language: A programmingLanguageId (e.g. ``TypeScript``); inferred
                from code_file's extension when omitted.
            code: The full bot source.
            code_file: Absolute path of a local source file, instead of code.
            opponents: The other seats: "boss" (the league boss / default AI),
                "self" (this same code), or an arena agentId (see
                get_arena_status / get_arena_battles). Defaults to enough
                bosses for the minimum player count.
            games: Number of games (1 to 20).
            seed: Referee input to replay a given game, e.g. ``seed=123`` (from
                a previous result); a fresh one per game when omitted.
            rotate_seats: Move your bot to the next seat each game, so a
                series is not biased by who plays first.
            stderr_tail: Include the last N lines your bot wrote to stderr in
                each game (0 = none).
        """
        if games < 1 or games > _MAX_GAMES:
            raise ValueError(f"games must be between 1 and {_MAX_GAMES}, got {games}")
        code, language = _load_code(code, code_file, language)
        client = await get_client()
        session = await client.get_arena_session(pretty_id)
        low = session.question.get("nbPlayersMin") or 2
        high = session.question.get("nbPlayersMax") or low
        if opponents is None:
            opponents = ["boss"] * (low - 1)
        seats = 1 + len(opponents)
        if not low <= seats <= high:
            raise ValueError(f"this game takes {low} to {high} players, got {seats}")

        others: list[tuple[int, str]] = []
        for opponent in opponents:
            if opponent == "boss":
                others.append((_BOSS_AGENT, "boss"))
            elif opponent == "self":
                others.append((_SELF_AGENT, "self"))
            else:
                try:
                    others.append((int(opponent), f"agent {int(opponent)}"))
                except (TypeError, ValueError):
                    raise ValueError(
                        f'opponent must be "boss", "self" or an agentId, got {opponent!r}'
                    ) from None

        summaries = []
        for index in range(games):
            seat = index % seats if rotate_seats else 0
            lineup = others[:seat] + [(_SELF_AGENT, "me")] + others[seat:]
            result = await client.play_game(
                session.handle,
                language,
                code,
                [agent for agent, _ in lineup],
                seed,
            )
            names = {i: label for i, (_, label) in enumerate(lineup)}
            summaries.append(_game_summary(result, seat, names, stderr_tail))
        return {
            "games": games,
            **_tally([s["outcome"] for s in summaries]),
            "results": summaries,
        }

    @mcp.tool()
    async def submit_arena_bot(
        pretty_id: str,
        language: str | None = None,
        code: str | None = None,
        code_file: str | None = None,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        """Submit a bot to a multiplayer arena (REPLACES your ranked agent).

        The new agent then plays ranking games against the league room, which
        takes minutes; poll get_arena_status (``percentage`` reaches 100) or
        pass ``wait_seconds`` to wait here. Promotion to the next league
        happens when your final score beats the boss's.

        Args:
            pretty_id: The multi puzzle's pretty id.
            language: A programmingLanguageId; inferred from code_file's
                extension when omitted.
            code: The full bot source.
            code_file: Absolute path of a local source file, instead of code.
            wait_seconds: Wait up to this long (0 to 900) for the ranking
                games to finish before returning.
        """
        if wait_seconds < 0 or wait_seconds > 900:
            raise ValueError(f"wait_seconds must be between 0 and 900, got {wait_seconds}")
        code, language = _load_code(code, code_file, language)
        client = await get_client()
        submission_id, ranking = await client.submit_arena(
            pretty_id, language, code, wait=wait_seconds
        )
        return {
            "submissionId": submission_id,
            "rank": ranking.localRank if ranking.localRank is not None else ranking.rank,
            "total": ranking.total,
            "score": ranking.score,
            "league": _league(ranking.league),
            "agentId": ranking.agentId,
            "percentage": ranking.percentage,
            "inProgress": ranking.inProgress,
        }


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
