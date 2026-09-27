"""CodinGame internal service paths.

The CodinGame API is undocumented and lives at::

    https://www.codingame.com/services/{Service}/{func}

Each call is an HTTP POST whose body is a JSON array of positional arguments.
Keeping every path as a named constant here means a CodinGame-side rename is a
one-line fix and gives the live tests a single source of truth to assert against.

All paths below were verified against the live API (June 2026). The number in
the trailing comment is the positional argument count the service expects; an
"Service not found: x.y(N)" error from CodinGame means the arg count is wrong.
"""

from __future__ import annotations

# --- Session / auth -------------------------------------------------------
# Returns the current session; when the rememberMe cookie is set it includes
# the logged-in codingamer. Used as our "whoami" + cookie validity check.
SESSION_FIND = ("Session", "findSession")  # 0 args

# --- CodinGamer (user) ----------------------------------------------------
# Public handle -> codingamer details + codingame points stats (progress).
USER_POINTS_STATS_BY_HANDLE = ("CodinGamer", "findCodingamePointsStatsByHandle")  # 1 arg: [publicHandle]
# Numeric user id -> public information.
USER_PUBLIC_INFO_BY_ID = ("CodinGamer", "findCodinGamerPublicInformations")  # 1 arg: [userId]

# --- Puzzles --------------------------------------------------------------
# userId -> all puzzles with the owner's *minimal* progress (requires the
# authenticated user to be the owner of that userId). "Minimal" means the
# entries carry only the puzzle id + progress -- no prettyId/title. Use it to
# enumerate ids, then hydrate them with PUZZLES_PROGRESS_BY_IDS.
PUZZLES_ALL_MINIMAL_PROGRESS = ("Puzzle", "findAllMinimalProgress")  # 1 arg: [userId]
# [ids] + userId -> full progress (incl. prettyId + title) for those puzzles.
# The trailing arg is a flag the website always sends as 1.
PUZZLES_PROGRESS_BY_IDS = ("Puzzle", "findProgressByIds")  # 3 args: [ids, userId, 1]
# prettyId + userId -> single puzzle detail with the owner's progress.
PUZZLE_PROGRESS_BY_PRETTY_ID = ("Puzzle", "findProgressByPrettyId")  # 2 args: [prettyId, userId]
# userId + puzzleId -> the puzzles CodinGame recommends tackling next.
PUZZLE_BEST_FOLLOWING_PROGRESS = ("Puzzle", "findBestFollowingProgress")  # 2 args: [userId, puzzleId]
# userId + prettyId + report flag -> a test-session handle for the puzzle's IDE.
PUZZLE_GENERATE_SESSION = ("Puzzle", "generateSessionFromPuzzlePrettyId")  # 3 args: [userId, prettyId, False]

# --- Leaderboards ---------------------------------------------------------
# leaderboardId + userId + scope + filter -> a puzzle's leaderboard (one entry
# per user and language; on a multi puzzle, one per agent across every league,
# carrying agentId and league). The leaderboard id is the puzzle's
# ``puzzleLeaderboardId`` (often the prettyId, but not always: "thor-codesize"
# for "power-of-thor"). Public: works without the cookie, userId may be null.
# The filter is {"active": bool, "column": ..., "filter": value}, one column at
# a time: "LANGUAGE" (a programmingLanguageId), "KEYWORD" (a pseudo substring)
# or, on a multi puzzle, "LEAGUE" (the lowercase name: "gold", "wood 1");
# the response is capped at 1000 entries (``filteredCount`` gives the real size).
PUZZLE_LEADERBOARD = ("Leaderboards", "getFilteredPuzzleLeaderboard")  # 4 args: [leaderboardId, userId, "global", filter]

# --- Test session (IDE) ---------------------------------------------------
# A session handle -> the puzzle's question: statement, stub generator,
# available languages, and the visible test cases (I/O referenced by binary id).
TEST_SESSION_START = ("TestSession", "startTestSession")  # 1 arg: [sessionHandle]

# --- Test session (writes) ------------------------------------------------
# Run a single visible test case. The second arg is the play request; the code
# is also persisted as the session's answer (so there is no separate "save").
# multipleLanguages.testIndex selects which test case (1-based) to run.
TEST_SESSION_PLAY = ("TestSession", "play")  # 2 args: [handle, {code, programmingLanguageId, multipleLanguages: {testIndex}}]
# Submit a solution for official grading. Returns a submission id (an integer);
# the per-validator result is then polled via REPORT_BY_SUBMISSION. The trailing
# arg is always null on the website.
TEST_SESSION_SUBMIT = ("TestSession", "submit")  # 3 args: [handle, {code, programmingLanguageId}, null]
# A submission id -> its grading report. Returns {"validatorShareable": false}
# while grading is still running, then the full report (score, validators, ...).
REPORT_BY_SUBMISSION = ("Report", "findReportBySubmission")  # 1 arg: [submissionId]

# --- Multiplayer (bot programming arenas) --------------------------------
# A multi puzzle's test session has no test cases: ``TestSession/play`` (above)
# runs one *game* instead, when the answer carries a ``multi`` block:
#   {code, programmingLanguageId,
#    multi: {agentsIds: [...], gameOptions: "seed=..." | null}}
# agentsIds lists the players in seat order: -1 is the code being played, -2
# the league boss (or the default AI), a positive id a submitted arena agent.
# Without the ``multi`` block, play fails with INVALID_MULTI_ANSWER. Arena
# submission is the plain TEST_SESSION_SUBMIT; its grading is not a report but
# the agent's ranking climbing to percentage 100 (ARENA_USER_RANKING).
#
# handle + userId -> the user's own ranking in their arena room: rank/total,
# score, league, agentId, and the submission's progress (percentage,
# inProgress). ~800 chars; what the IDE polls after a submit.
ARENA_USER_RANKING = ("Leaderboards", "getUserArenaDivisionRoomRankingByTestSessionHandle")  # 2 args: [handle, userId]
# {divisionId, roomIndex} + publicHandle + scope + filter -> one league room's
# leaderboard. The boss comes first (no rank, carries ``arenaboss``); every
# entry has an ``agentId`` that play accepts as an opponent. ~660k chars for
# 1200 entries, capped at 1000.
ARENA_ROOM_LEADERBOARD = ("Leaderboards", "getFilteredArenaDivisionRoomLeaderboard")  # 4 args: [{divisionId, roomIndex}, publicHandle, "global", filter]
# handle -> the user's agent's last arena battles: gameId, done, and players
# (playerAgentId, userId, nickname, position). ``position`` is the player's
# *finishing place* (0 = winner, ties share it: a draw is 0/0), not its seat
# -- the seat is the replay's ``agents[].index``.
ARENA_LAST_BATTLES = ("gamesPlayersRanking", "findLastBattlesByTestSessionHandle")  # 2 args: [handle, null]
# agentId -> the same, for *any* arena agent (e.g. a top player's, from the
# puzzle leaderboard): ~240 battles for a Legend agent. Public.
ARENA_LAST_BATTLES_BY_AGENT = ("gamesPlayersRanking", "findLastBattlesByAgentId")  # 2 args: [agentId, null]
# gameId + userId -> a replay: frames (per-turn stdout/stderr/summary/view),
# agents (index = seat), refereeInput (the seed). Works on anyone's game; only
# the user's own stderr is visible. ``scores`` are per seat but ``ranks`` is
# the *seats in finishing order* ([1, 3, 2, 0]: seat 1 won), with no ties:
# equal scores are what mark a shared place. ~200k chars for 500 frames.
GAME_RESULT_BY_ID = ("gameResult", "findByGameId")  # 2 args: [gameId, userId]

# --- Puzzle topics (labels) -----------------------------------------------
# userId + puzzleId -> the puzzle's topics/labels as a tree, each carrying the
# user's "learned" (claimed) flag.
PUZZLE_TOPICS_BY_USER = ("CodingamerPuzzleTopic", "selectTopicsByCodingamerIdAndPuzzleId")  # 2 args: [userId, puzzleId]
# Claim (mark as learned) a single leaf label. Returns 204 with no body.
PUZZLE_TOPIC_MARK_LEARNED = ("CodingamerPuzzleTopic", "markAsLearned")  # 4 args: [userId, puzzleId, topicId, True]

# --- Account meta ---------------------------------------------------------
# Light counters the website polls for the navbar/dashboard.
NOTIFICATIONS_UNSEEN = ("Notification", "findUnseenNotifications")  # 1 arg: [userId]
QUESTS_LOOTABLE_COUNT = ("Quest", "countLootableQuests")  # 1 arg: [userId]
CONTRIBUTIONS_NEW_COUNT = ("Contribution", "findNewContributionCount")  # 2 args: [userId, sinceEpochMs]
FEATURED_EVENTS_NEW_COUNT = ("FeaturedEvent", "findNewFeaturedEventCount")  # 1 arg: [userId]
