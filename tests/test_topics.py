"""Unit tests for puzzle-topic leaf selection (pure, no network)."""

from __future__ import annotations

import copy

from codingame_mcp.client import unclaimed_leaf_topics
from codingame_mcp.models import PuzzleTopic

# Captured from CodingamerPuzzleTopic/selectTopicsByCodingamerIdAndPuzzleId:
# two category parents, each wrapping a single claimable leaf.
SAMPLE = [
    {
        "learned": False,
        "id": 41,
        "handle": "algorithms",
        "category": "INTERMEDIATE",
        "value": "Algorithmes",
        "children": [
            {
                "learned": False,
                "id": 67,
                "handle": "parsing",
                "contentDetailsId": 102,
                "category": "FUNDAMENTALS",
                "value": "Parsing",
                "children": [],
            }
        ],
    },
    {
        "learned": False,
        "id": 93,
        "handle": "uncategorized",
        "value": "Sans catégorie",
        "children": [
            {
                "learned": False,
                "id": 128,
                "handle": "ascii-art",
                "category": "INTERMEDIATE",
                "value": "Ascii Art",
                "children": [],
            }
        ],
    },
]


def _parse(raw):
    return [PuzzleTopic.model_validate(t) for t in raw]


def test_returns_unlearned_leaves_not_parents():
    leaves = unclaimed_leaf_topics(_parse(SAMPLE))
    assert {t.id for t in leaves} == {67, 128}


def test_skips_already_learned_leaf():
    raw = copy.deepcopy(SAMPLE)
    raw[0]["children"][0]["learned"] = True  # claim "parsing"
    leaves = unclaimed_leaf_topics(_parse(raw))
    assert {t.id for t in leaves} == {128}
