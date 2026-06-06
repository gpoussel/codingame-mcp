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

# --- Test session (IDE) ---------------------------------------------------
# A session handle -> the puzzle's question: statement, stub generator,
# available languages, and the visible test cases (I/O referenced by binary id).
TEST_SESSION_START = ("TestSession", "startTestSession")  # 1 arg: [sessionHandle]

# --- Account meta ---------------------------------------------------------
# Light counters the website polls for the navbar/dashboard.
NOTIFICATIONS_UNSEEN = ("Notification", "findUnseenNotifications")  # 1 arg: [userId]
QUESTS_LOOTABLE_COUNT = ("Quest", "countLootableQuests")  # 1 arg: [userId]
CONTRIBUTIONS_NEW_COUNT = ("Contribution", "findNewContributionCount")  # 2 args: [userId, sinceEpochMs]
FEATURED_EVENTS_NEW_COUNT = ("FeaturedEvent", "findNewFeaturedEventCount")  # 1 arg: [userId]
