"""Async HTTP client for the undocumented CodinGame API.

Every call is an HTTP POST to ``/services/{Service}/{func}`` whose body is a
JSON array of positional arguments. Authentication is via the ``rememberMe``
cookie set on the ``www.codingame.com`` domain.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from . import endpoints
from .models import (
    ArenaBattle,
    ArenaRanking,
    ArenaRoomLeaderboard,
    ArenaSession,
    CodinGamer,
    GameResult,
    PointsStats,
    PuzzleLanguage,
    PuzzleLeaderboard,
    PuzzleProgress,
    PuzzleTestCase,
    PuzzleTests,
    PuzzleTopic,
    SubmitReport,
    TestPlayResult,
)

BASE_URL = "https://www.codingame.com"
# A multi game is played server-side during the request: long games (100+
# turns at up to ~100 ms per bot) take well over the default timeout.
PLAY_TIMEOUT = 180.0
API_URL = BASE_URL + "/services/"
# Puzzle test-case I/O are served as plain-text blobs from the static CDN,
# addressed by the binary ids embedded in the test session.
FILE_SERVLET_URL = "https://static.codingame.com/servlet/fileservlet"
COOKIE_DOMAIN = "www.codingame.com"
REMEMBER_ME_COOKIE = "rememberMe"


def unclaimed_leaf_topics(topics: list[PuzzleTopic]) -> list[PuzzleTopic]:
    """Flatten a topic tree to the leaf labels not yet claimed.

    Only leaves (topics with no ``children``) are claimable; category parents
    are skipped. A leaf counts as claimable when its ``learned`` flag is falsy.
    """
    leaves: list[PuzzleTopic] = []
    for topic in topics:
        if topic.children:
            leaves.extend(unclaimed_leaf_topics(topic.children))
        elif not topic.learned:
            leaves.append(topic)
    return leaves


class CodinGameError(RuntimeError):
    """An error returned by the CodinGame API.

    CodinGame signals errors with a JSON envelope such as
    ``{"id": -3, "message": "Service not found: ..."}`` or
    ``{"id": 404}``.
    """

    def __init__(self, service: str, func: str, payload: Any):
        self.service = service
        self.func = func
        self.payload = payload
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("id") or payload)
        super().__init__(f"{service}/{func} failed: {message or payload}")


class LoginError(CodinGameError):
    """The rememberMe cookie is missing, invalid, or expired."""


class CodinGameClient:
    """Read-only async client for the CodinGame internal API."""

    def __init__(self, remember_me: str, *, timeout: float = 20.0):
        self._remember_me = remember_me
        self._client = httpx.AsyncClient(
            base_url=API_URL,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        self._client.cookies.set(REMEMBER_ME_COOKIE, remember_me, domain=COOKIE_DOMAIN)
        # Cache the authenticated user id, resolved lazily from the session.
        self._user_id: int | None = None
        self._public_handle: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CodinGameClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- low level ---------------------------------------------------------

    async def request(
        self,
        service: str,
        func: str,
        parameters: list | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """POST a positional-argument array to a CodinGame service and return JSON.

        Raises:
            CodinGameError: on a non-2xx status or a CodinGame error envelope.
        """
        url = f"{service}/{func}"
        extra = {"timeout": timeout} if timeout is not None else {}
        response = await self._client.post(url, json=parameters or [], **extra)
        if response.status_code >= 400:
            payload: Any
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            raise CodinGameError(service, func, payload)
        if response.status_code == 204 or not response.content:
            # No content (e.g. markAsLearned returns 204): nothing to parse.
            return None
        data = response.json()
        if isinstance(data, dict) and data.get("id", 0) and "message" in data:
            # CodinGame error envelope returned with a 200 status.
            raise CodinGameError(service, func, data)
        return data

    async def _call(
        self,
        endpoint: tuple[str, str],
        parameters: list | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        return await self.request(endpoint[0], endpoint[1], parameters, timeout=timeout)

    # -- auth --------------------------------------------------------------

    async def login_verify(self) -> CodinGamer:
        """Validate the cookie and return the authenticated codingamer.

        Calls ``Session/findSession``; when the rememberMe cookie is valid the
        session carries the logged-in codingamer.

        Raises:
            LoginError: if the session is anonymous (cookie missing/expired).
        """
        session = await self._call(endpoints.SESSION_FIND)
        codingamer_data = None
        if isinstance(session, dict):
            codingamer_data = session.get("codinGamer") or session.get("codingamer")
        if not codingamer_data:
            raise LoginError(
                *endpoints.SESSION_FIND,
                {"message": "Not logged in: the rememberMe cookie is missing or expired."},
            )
        codingamer = CodinGamer.model_validate(codingamer_data)
        self._user_id = codingamer.userId
        self._public_handle = codingamer.publicHandle
        return codingamer

    async def get_user_id(self) -> int:
        """Return the authenticated user's numeric id, resolving it if needed."""
        if self._user_id is None:
            await self.login_verify()
        if self._user_id is None:
            raise LoginError(
                *endpoints.SESSION_FIND,
                {"message": "Could not resolve authenticated user id."},
            )
        return self._user_id

    # -- users -------------------------------------------------------------

    async def get_points_stats(self, handle: str) -> PointsStats:
        """Fetch a codingamer's details and points/progress by public handle."""
        data = await self._call(endpoints.USER_POINTS_STATS_BY_HANDLE, [handle])
        if data is None:
            raise CodinGameError(
                *endpoints.USER_POINTS_STATS_BY_HANDLE,
                {"message": f"No codingamer found for handle {handle!r}."},
            )
        return PointsStats.model_validate(data)

    async def get_public_info(self, user_id: int) -> CodinGamer:
        """Fetch a codingamer's public information by numeric id."""
        data = await self._call(endpoints.USER_PUBLIC_INFO_BY_ID, [user_id])
        return CodinGamer.model_validate(data)

    # -- puzzles -----------------------------------------------------------

    async def list_puzzles(self, user_id: int | None = None) -> list[PuzzleProgress]:
        """List all puzzles with the authenticated user's progress.

        ``findAllMinimalProgress`` only returns puzzle ids and progress (no
        ``prettyId``/``title``), so we enumerate the ids there and hydrate them
        in a single ``findProgressByIds`` call -- mirroring what the website
        does. CodinGame only returns progress to the owner, so ``user_id``
        defaults to the authenticated user.
        """
        uid = user_id if user_id is not None else await self.get_user_id()
        minimal = await self._call(endpoints.PUZZLES_ALL_MINIMAL_PROGRESS, [uid])
        ids = [item["id"] for item in (minimal or []) if item.get("id") is not None]
        if not ids:
            return []
        data = await self._call(endpoints.PUZZLES_PROGRESS_BY_IDS, [ids, uid, 1])
        return [PuzzleProgress.model_validate(item) for item in (data or [])]

    async def get_puzzle(self, pretty_id: str, user_id: int | None = None) -> PuzzleProgress:
        """Fetch a single puzzle (by pretty id) with the user's progress."""
        uid = user_id if user_id is not None else await self.get_user_id()
        data = await self._call(endpoints.PUZZLE_PROGRESS_BY_PRETTY_ID, [pretty_id, uid])
        if data is None:
            raise CodinGameError(
                *endpoints.PUZZLE_PROGRESS_BY_PRETTY_ID,
                {"message": f"No puzzle found for pretty id {pretty_id!r}."},
            )
        return PuzzleProgress.model_validate(data)

    async def recommend_next_puzzles(
        self, pretty_id: str, user_id: int | None = None
    ) -> list[PuzzleProgress]:
        """Puzzles CodinGame recommends after the given one (may be empty).

        Resolves ``pretty_id`` to its numeric id, then asks
        ``findBestFollowingProgress`` for the user's suggested next puzzles.
        """
        uid = user_id if user_id is not None else await self.get_user_id()
        puzzle = await self.get_puzzle(pretty_id, uid)
        data = await self._call(
            endpoints.PUZZLE_BEST_FOLLOWING_PROGRESS, [uid, puzzle.id]
        )
        return [PuzzleProgress.model_validate(item) for item in (data or [])]

    async def get_puzzle_leaderboard(
        self, leaderboard_id: str, language: str | None = None
    ) -> PuzzleLeaderboard:
        """Fetch a puzzle leaderboard, optionally filtered to one language.

        ``leaderboard_id`` is the puzzle's ``puzzleLeaderboardId`` (see
        :meth:`get_puzzle`). The endpoint is public and capped at 1000 entries.
        """
        leaderboard_filter = (
            {"active": True, "column": "LANGUAGE", "filter": language}
            if language
            else {"active": False, "column": "", "filter": ""}
        )
        data = await self._call(
            endpoints.PUZZLE_LEADERBOARD,
            [leaderboard_id, None, "global", leaderboard_filter],
        )
        return PuzzleLeaderboard.model_validate(data or {})

    async def get_puzzle_tests(
        self, pretty_id: str, user_id: int | None = None, *, resolve_io: bool = True
    ) -> PuzzleTests:
        """Open a test session for a puzzle and return its solving material.

        Returns the statement, the stub generator spec, the available languages,
        and the visible test cases. When ``resolve_io`` is true (default), each
        test case's input/output blob is fetched and inlined as text.
        """
        uid = user_id if user_id is not None else await self.get_user_id()
        session = await self._call(
            endpoints.PUZZLE_GENERATE_SESSION, [uid, pretty_id, False]
        )
        handle = session.get("handle") if isinstance(session, dict) else None
        if not handle:
            raise CodinGameError(
                *endpoints.PUZZLE_GENERATE_SESSION,
                {"message": f"No test session for pretty id {pretty_id!r}."},
            )
        data = await self._call(endpoints.TEST_SESSION_START, [handle])
        question = (data or {}).get("currentQuestion", {}).get("question", {})
        tests = PuzzleTests(
            prettyId=pretty_id,
            title=question.get("title"),
            statement=question.get("statement"),
            stubGenerator=question.get("stubGenerator"),
            availableLanguages=[
                PuzzleLanguage.model_validate(lang)
                for lang in (question.get("availableLanguages") or [])
            ],
            testCases=[
                PuzzleTestCase.model_validate(tc)
                for tc in (question.get("testCases") or [])
            ],
        )
        if resolve_io:
            await self._inline_test_io(tests.testCases)
        return tests

    async def _inline_test_io(self, test_cases: list[PuzzleTestCase]) -> None:
        """Fetch and inline each test case's input/output text, concurrently."""
        jobs: list[tuple[PuzzleTestCase, str, int]] = []
        for tc in test_cases:
            if tc.inputBinaryId is not None:
                jobs.append((tc, "testIn", tc.inputBinaryId))
            if tc.outputBinaryId is not None:
                jobs.append((tc, "testOut", tc.outputBinaryId))
        blobs = await asyncio.gather(*(self._fetch_blob(bid) for _, _, bid in jobs))
        for (tc, attr, _), text in zip(jobs, blobs):
            setattr(tc, attr, text)

    async def _fetch_blob(self, binary_id: int) -> str | None:
        """Fetch a static text blob (test I/O) by its binary id."""
        response = await self._client.get(FILE_SERVLET_URL, params={"id": binary_id})
        if response.status_code >= 400:
            return None
        return response.text

    # -- writes (test session) ---------------------------------------------

    async def _open_session(self, pretty_id: str, user_id: int | None = None) -> str:
        """Open a test session for a puzzle and return its handle."""
        uid = user_id if user_id is not None else await self.get_user_id()
        session = await self._call(
            endpoints.PUZZLE_GENERATE_SESSION, [uid, pretty_id, False]
        )
        handle = session.get("handle") if isinstance(session, dict) else None
        if not handle:
            raise CodinGameError(
                *endpoints.PUZZLE_GENERATE_SESSION,
                {"message": f"No test session for pretty id {pretty_id!r}."},
            )
        return handle

    async def run_tests(
        self,
        pretty_id: str,
        language: str,
        code: str,
        test_indexes: list[int] | None = None,
        user_id: int | None = None,
    ) -> list[TestPlayResult]:
        """Run a puzzle's visible test cases against ``code`` and return results.

        ``TestSession/play`` runs a single test case, so we open one session and
        play each requested case (all of them by default). A session allows only
        one executor at a time, so the runs are sequential. Running also persists
        ``code`` as the session's answer, so there is no separate save step.
        ``language`` is a ``programmingLanguageId`` (e.g. ``Python3``,
        ``TypeScript``); see ``get_puzzle_tests`` for the valid ids.
        """
        handle = await self._open_session(pretty_id, user_id)
        started = await self._call(endpoints.TEST_SESSION_START, [handle])
        question = (started or {}).get("currentQuestion", {}).get("question", {})
        cases = question.get("testCases") or []
        label_by_index = {tc.get("index"): tc.get("label") for tc in cases}
        if test_indexes is None:
            test_indexes = [tc.get("index") for tc in cases if tc.get("index") is not None]

        results: list[TestPlayResult] = []
        for index in test_indexes:
            payload = {
                "code": code,
                "programmingLanguageId": language,
                "multipleLanguages": {"testIndex": index},
            }
            data = await self._call(endpoints.TEST_SESSION_PLAY, [handle, payload])
            result = TestPlayResult.model_validate(data or {})
            result.index = index
            result.label = label_by_index.get(index)
            results.append(result)
        return results

    async def submit(
        self,
        pretty_id: str,
        language: str,
        code: str,
        user_id: int | None = None,
        *,
        poll: bool = True,
        max_polls: int = 30,
        poll_interval: float = 1.0,
    ) -> SubmitReport:
        """Submit ``code`` for official grading and return the report.

        ``TestSession/submit`` returns only a submission id; grading is async, so
        we poll ``Report/findReportBySubmission`` until it carries a ``score``
        (CodinGame returns ``{"validatorShareable": false}`` until then). With
        ``poll=False`` the report holds just the submission id. **This affects
        the puzzle's score/ranking** -- unlike :meth:`run_tests`.
        """
        handle = await self._open_session(pretty_id, user_id)
        payload = {"code": code, "programmingLanguageId": language}
        submission_id = await self._call(
            endpoints.TEST_SESSION_SUBMIT, [handle, payload, None]
        )
        if not poll:
            return SubmitReport(submissionId=submission_id)

        report: Any = None
        for _ in range(max_polls):
            report = await self._call(endpoints.REPORT_BY_SUBMISSION, [submission_id])
            if isinstance(report, dict) and report.get("score") is not None:
                return SubmitReport.model_validate(report)
            await asyncio.sleep(poll_interval)
        # Grading did not finish in time: return whatever the last poll held.
        if isinstance(report, dict):
            report.setdefault("submissionId", submission_id)
            return SubmitReport.model_validate(report)
        return SubmitReport(submissionId=submission_id)

    # -- multiplayer (arenas) ----------------------------------------------

    async def get_arena_session(
        self, pretty_id: str, user_id: int | None = None
    ) -> ArenaSession:
        """Open a multi puzzle's test session: league, draft and question.

        The question's ``viewer`` (the game's JS bundle, ~100k+ chars) is kept;
        callers presenting the session should drop it.
        """
        handle = await self._open_session(pretty_id, user_id)
        data = await self._call(endpoints.TEST_SESSION_START, [handle])
        current = (data or {}).get("currentQuestion") or {}
        return ArenaSession(
            handle=handle,
            arena=current.get("arena"),
            hasAgent=current.get("hasAgent"),
            answer=current.get("answer"),
            question=current.get("question") or {},
        )

    async def play_game(
        self,
        handle: str,
        language: str,
        code: str,
        agents_ids: list[int],
        game_options: str | None = None,
    ) -> GameResult:
        """Play one game of a multi puzzle in the IDE and return it.

        ``agents_ids`` lists the seats in order: -1 is ``code``, -2 the league
        boss, a positive id a submitted arena agent. ``game_options`` is the
        referee input (e.g. ``"seed=123"``) to replay a given game; None lets
        the referee draw one. Like a puzzle test run, this persists ``code`` as
        the session draft. One executor per session: play games sequentially.
        """
        payload = {
            "code": code,
            "programmingLanguageId": language,
            "multi": {"agentsIds": agents_ids, "gameOptions": game_options},
        }
        data = await self._call(
            endpoints.TEST_SESSION_PLAY, [handle, payload], timeout=PLAY_TIMEOUT
        )
        return GameResult.model_validate(data or {})

    async def get_arena_ranking(
        self, handle: str, user_id: int | None = None
    ) -> ArenaRanking:
        """The user's ranking in their arena room (incl. submission progress)."""
        uid = user_id if user_id is not None else await self.get_user_id()
        data = await self._call(endpoints.ARENA_USER_RANKING, [handle, uid])
        return ArenaRanking.model_validate(data or {})

    async def get_arena_room_leaderboard(
        self, division_id: int, room_index: int = 0
    ) -> ArenaRoomLeaderboard:
        """A league room's leaderboard (boss first, capped at 1000 entries)."""
        if self._public_handle is None:
            await self.login_verify()
        data = await self._call(
            endpoints.ARENA_ROOM_LEADERBOARD,
            [
                {"divisionId": division_id, "roomIndex": room_index},
                self._public_handle,
                "global",
                {"active": False, "column": "", "filter": ""},
            ],
        )
        return ArenaRoomLeaderboard.model_validate(data or {})

    async def get_last_battles(self, handle: str) -> list[ArenaBattle]:
        """The user's agent's last arena battles, most recent first."""
        data = await self._call(endpoints.ARENA_LAST_BATTLES, [handle, None])
        return [ArenaBattle.model_validate(b) for b in (data or [])]

    async def get_game_result(
        self, game_id: int, user_id: int | None = None
    ) -> GameResult:
        """Fetch a game's replay (frames, ranks, scores, agents, seed)."""
        uid = user_id if user_id is not None else await self.get_user_id()
        data = await self._call(endpoints.GAME_RESULT_BY_ID, [game_id, uid])
        if not data:
            raise CodinGameError(
                *endpoints.GAME_RESULT_BY_ID,
                {"message": f"No game found for id {game_id!r}."},
            )
        return GameResult.model_validate(data)

    async def submit_arena(
        self,
        pretty_id: str,
        language: str,
        code: str,
        user_id: int | None = None,
        *,
        wait: float = 0.0,
        poll_interval: float = 10.0,
    ) -> tuple[int | None, ArenaRanking]:
        """Submit a bot to its arena; return the submission id and ranking.

        The arena grades a submission by playing it against the room, which
        takes minutes: there is no report, the new agent's ranking just climbs
        to ``percentage`` 100. With ``wait`` > 0, poll the ranking for up to
        ``wait`` seconds until the *new* agent (its ``agentId`` differs from
        the one before the submit) has finished. **This replaces the user's
        arena agent and changes their ranking.**
        """
        handle = await self._open_session(pretty_id, user_id)

        async def ranking_or_empty() -> ArenaRanking:
            # League-less (old BOT_PROGRAMMING) puzzles have no arena room:
            # the ranking call fails with "internal error". The submission
            # itself works, so a missing ranking must not block it.
            try:
                return await self.get_arena_ranking(handle, user_id)
            except CodinGameError:
                return ArenaRanking()

        before = await ranking_or_empty()
        payload = {"code": code, "programmingLanguageId": language}
        submission_id = await self._call(
            endpoints.TEST_SESSION_SUBMIT, [handle, payload, None]
        )
        ranking = await ranking_or_empty()
        deadline = asyncio.get_running_loop().time() + wait
        while asyncio.get_running_loop().time() < deadline and not (
            ranking.agentId is not None
            and ranking.agentId != before.agentId
            and ranking.percentage == 100
            and not ranking.inProgress
        ):
            await asyncio.sleep(poll_interval)
            ranking = await ranking_or_empty()
        return submission_id, ranking

    # -- puzzle topics (labels) --------------------------------------------

    async def _select_topics(self, user_id: int, puzzle_id: int) -> list[PuzzleTopic]:
        data = await self._call(endpoints.PUZZLE_TOPICS_BY_USER, [user_id, puzzle_id])
        return [PuzzleTopic.model_validate(t) for t in (data or [])]

    async def get_puzzle_topics(
        self, pretty_id: str, user_id: int | None = None
    ) -> list[PuzzleTopic]:
        """Return a puzzle's topics/labels as a tree, with the user's claims."""
        uid = user_id if user_id is not None else await self.get_user_id()
        puzzle = await self.get_puzzle(pretty_id, uid)
        if puzzle.id is None:
            raise CodinGameError(
                *endpoints.PUZZLE_PROGRESS_BY_PRETTY_ID,
                {"message": f"No puzzle id for pretty id {pretty_id!r}."},
            )
        return await self._select_topics(uid, puzzle.id)

    async def claim_puzzle_labels(
        self, pretty_id: str, user_id: int | None = None
    ) -> list[PuzzleTopic]:
        """Claim (mark as learned) every unclaimed leaf label of a puzzle.

        Only leaf topics are claimable, one ``markAsLearned`` call each (the
        endpoint takes a single topic and returns 204). Returns the labels that
        were claimed (empty if there was nothing left to claim). **Changes the
        user's profile.**
        """
        uid = user_id if user_id is not None else await self.get_user_id()
        puzzle = await self.get_puzzle(pretty_id, uid)
        if puzzle.id is None:
            raise CodinGameError(
                *endpoints.PUZZLE_PROGRESS_BY_PRETTY_ID,
                {"message": f"No puzzle id for pretty id {pretty_id!r}."},
            )
        topics = await self._select_topics(uid, puzzle.id)
        claimable = [t for t in unclaimed_leaf_topics(topics) if t.id is not None]
        for topic in claimable:
            await self._call(
                endpoints.PUZZLE_TOPIC_MARK_LEARNED, [uid, puzzle.id, topic.id, True]
            )
        return claimable

    # -- account meta ------------------------------------------------------

    async def get_account_summary(
        self, user_id: int | None = None, *, contributions_since: int = 0
    ) -> dict[str, Any]:
        """Return the lightweight counters the website polls for the navbar.

        Bundles unseen notifications plus the lootable-quest, new-contribution,
        and new-featured-event counts in one round of concurrent calls.
        ``contributions_since`` is an epoch-millisecond cutoff (0 = all).
        """
        uid = user_id if user_id is not None else await self.get_user_id()
        notifications, quests, contributions, events = await asyncio.gather(
            self._call(endpoints.NOTIFICATIONS_UNSEEN, [uid]),
            self._call(endpoints.QUESTS_LOOTABLE_COUNT, [uid]),
            self._call(endpoints.CONTRIBUTIONS_NEW_COUNT, [uid, contributions_since]),
            self._call(endpoints.FEATURED_EVENTS_NEW_COUNT, [uid]),
        )
        return {
            "unseenNotifications": notifications or [],
            "lootableQuestCount": quests,
            "newContributionCount": contributions,
            "newFeaturedEventCount": events,
        }
