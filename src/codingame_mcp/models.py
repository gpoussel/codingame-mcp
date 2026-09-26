"""Pydantic models for CodinGame API responses.

The CodinGame API is undocumented and its payloads can gain fields without
notice. Every model therefore uses ``extra="allow"`` so additive changes never
break parsing, and the fields we *rely on* are declared explicitly (mostly
Optional) to document our dependency surface. The live test suite asserts that
these declared fields are actually present on real responses, which is how we
detect breaking CodinGame-side changes without being brittle to data churn.

Models expose ``.model_dump()`` for serialization back through MCP tools, which
preserves both the declared and the extra fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CGModel(BaseModel):
    """Base model: tolerate unknown fields, populate by alias or name."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CodinGamer(CGModel):
    """A CodinGame user.

    Returned (nested) by points-stats and public-information endpoints.
    """

    userId: int | None = None
    pseudo: str | None = None
    publicHandle: str | None = None
    countryId: str | None = None
    level: int | None = None
    rank: int | None = None
    category: str | None = None
    tagline: str | None = None
    biography: str | None = None
    company: str | None = None
    school: str | None = None
    avatar: int | None = None
    cover: int | None = None


class PointsStats(CGModel):
    """A codingamer's CodinGame points / progress.

    Wrapper returned by ``CodinGamer/findCodingamePointsStatsByHandle``; carries
    both the codingamer and the points ranking breakdown.
    """

    codingamer: CodinGamer | None = None
    codingamePointsRankingDto: dict | None = None


class PuzzleProgress(CGModel):
    """A puzzle entry with the authenticated user's progress.

    Returned (in a list) by ``Puzzle/findProgressByIds`` and (singly, with the
    extra detail fields populated) by ``Puzzle/findProgressByPrettyId``. The
    detail-only fields (``statement``, ``topics``, ``xpPoints``, ...) are
    ``None`` on list entries, which carry just the id + progress.
    """

    id: int | None = None
    level: str | None = None
    title: str | None = None
    prettyId: str | None = None
    solvedCount: int | None = None
    attemptCount: int | None = None
    creationTime: int | None = None
    # Per-user progress.
    rank: int | None = None
    validatorScore: int | None = None
    submitted: bool | None = None
    communityCreation: bool | None = None
    # Detail fields, populated only by findProgressByPrettyId.
    statement: str | None = None
    topics: list | None = None
    xpPoints: int | None = None
    type: str | None = None
    forumLink: str | None = None
    detailsPageUrl: str | None = None
    contributor: dict | None = None
    # The id of the puzzle's leaderboard (often, not always, the prettyId).
    puzzleLeaderboardId: str | None = None


class PuzzleLanguage(CGModel):
    """A programming language available for a puzzle's test session."""

    id: str | None = None
    name: str | None = None


class PuzzleTestCase(CGModel):
    """A visible test case for a puzzle.

    The actual input/output live as separate binary blobs referenced by id;
    :meth:`CodinGameClient.get_puzzle_tests` resolves them into ``testIn`` /
    ``testOut`` text unless asked not to.
    """

    index: int | None = None
    label: str | None = None
    inputBinaryId: int | None = None
    outputBinaryId: int | None = None
    testIn: str | None = None
    testOut: str | None = None


class TestPlayResult(CGModel):
    """One visible test case's run result, from ``TestSession/play``.

    ``index``/``label`` are carried over from the test case that was run (the
    play response itself only returns ``output`` + ``comparison``). On failure
    CodinGame adds fields such as ``error``/``expected``/``found``, kept via the
    base model's ``extra="allow"``.
    """

    index: int | None = None
    label: str | None = None
    output: str | None = None
    comparison: dict | None = None


class ValidatorResult(CGModel):
    """One validator (graded test case) result from a submission report."""

    name: str | None = None
    methodName: str | None = None
    success: bool | None = None
    difficulty: int | None = None


class SubmitReport(CGModel):
    """A submission's grading report, from ``Report/findReportBySubmission``.

    Populated once grading finishes (before then CodinGame returns only
    ``{"validatorShareable": false}``, i.e. ``score is None``).
    """

    submissionId: int | None = None
    score: float | None = None
    bestScore: float | None = None
    validators: list[ValidatorResult] = []


class PuzzleTopic(CGModel):
    """A puzzle topic/label, from ``CodingamerPuzzleTopic/selectTopics...``.

    Topics form a tree: category parents wrap claimable leaf labels in
    ``children``. ``learned`` says whether the authenticated user has already
    claimed it.
    """

    id: int | None = None
    handle: str | None = None
    value: str | None = None
    category: str | None = None
    contentDetailsId: int | None = None
    learned: bool | None = None
    children: list["PuzzleTopic"] = []


class PuzzleTests(CGModel):
    """A puzzle's IDE question: statement, stub, languages, and test cases.

    Assembled from ``TestSession/startTestSession`` -- the data an assistant
    needs to actually solve the puzzle.
    """

    prettyId: str | None = None
    title: str | None = None
    statement: str | None = None
    stubGenerator: str | None = None
    availableLanguages: list[PuzzleLanguage] = []
    testCases: list[PuzzleTestCase] = []


class LeaderboardEntry(CGModel):
    """One entry of a puzzle leaderboard (a user's best in one language).

    ``criteriaScore`` is the puzzle's optimization criterion (bytes on code-golf
    puzzles), ``score`` the validator percentage, and ``creationTime`` the
    submission time in epoch milliseconds.
    """

    rank: int | None = None
    pseudo: str | None = None
    score: float | None = None
    criteriaScore: float | None = None
    programmingLanguage: str | None = None
    creationTime: int | None = None
    codingamer: CodinGamer | None = None


class PuzzleLeaderboard(CGModel):
    """A puzzle leaderboard, from ``Leaderboards/getFilteredPuzzleLeaderboard``.

    ``users`` is capped at 1000 entries; ``count`` is the whole leaderboard and
    ``filteredCount`` the number of entries matching the filter.
    """

    users: list[LeaderboardEntry] = []
    count: int | None = None
    filteredCount: int | None = None
    criteria: str | None = None


class ArenaRanking(CGModel):
    """An agent's standing in its arena room.

    From ``Leaderboards/getUserArenaDivisionRoomRankingByTestSessionHandle``
    (the user's own) or as a room leaderboard entry. After a submit,
    ``percentage`` climbs to 100 while ``inProgress`` is true: that is the
    arena's equivalent of a grading report. The boss's entry has no ``rank``
    and carries ``arenaboss`` instead of ``codingamer``.
    """

    pseudo: str | None = None
    rank: int | None = None
    localRank: int | None = None
    total: int | None = None
    score: float | None = None
    league: dict | None = None
    agentId: int | None = None
    percentage: int | None = None
    inProgress: bool | None = None
    eligibleForPromotion: bool | None = None
    programmingLanguage: str | None = None
    arenaboss: dict | None = None
    codingamer: CodinGamer | None = None


class ArenaRoomLeaderboard(CGModel):
    """A league room's leaderboard, from ``getFilteredArenaDivisionRoomLeaderboard``.

    ``users`` is capped at 1000 (boss first); ``codingamerUserRank`` is the
    requesting user's own entry wherever it sits.
    """

    users: list[ArenaRanking] = []
    count: int | None = None
    codingamerUserRank: ArenaRanking | None = None


class ArenaSession(CGModel):
    """A multi puzzle's IDE state, from ``TestSession/startTestSession``.

    ``arena`` holds the user's league (``arenaCodinGamer.divisionId`` /
    ``roomIndex``, ``division.arenaboss``, ``league``, ``timeToPromotion``);
    ``answer`` the current draft; ``question`` the league's statement, stub and
    seat bounds (``nbPlayersMin``/``nbPlayersMax``).
    """

    handle: str
    arena: dict | None = None
    hasAgent: bool | None = None
    answer: dict | None = None
    question: dict = {}


class GameFrame(CGModel):
    """One frame of a game. ``agentId`` is the *seat index* (-1 on the init frame)."""

    agentId: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    summary: str | None = None
    gameInformation: str | None = None
    view: str | None = None
    keyframe: bool | None = None


class GameResult(CGModel):
    """A played game: ``TestSession/play`` on a multi puzzle, or a replay.

    ``ranks``/``scores`` are per seat (rank 0 is the winner, equal ranks a
    draw); ``refereeInput`` holds the seed (``seed=...``) that replays it.
    ``agents`` is only present on replays.
    """

    gameId: int | None = None
    refereeInput: str | None = None
    scores: list[float] = []
    ranks: list[int] = []
    tooltips: list[str] = []
    frames: list[GameFrame] = []
    agents: list[dict] = []


class ArenaBattle(CGModel):
    """One of the user's last arena battles (no outcome: see the replay)."""

    gameId: int | None = None
    done: bool | None = None
    players: list[dict] = []
