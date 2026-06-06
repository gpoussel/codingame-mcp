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
