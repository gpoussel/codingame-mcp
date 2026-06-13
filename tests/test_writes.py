"""Live tests for the write operations (run tests / submit).

These hit the real CodinGame API and are skipped without a cookie like the rest
of the suite. ``run_tests`` is side-effect-free (it just plays visible test
cases); the real ``submit`` is gated behind an explicit opt-in env var so the
suite never submits on its own.
"""

from __future__ import annotations

import os

import pytest

# A puzzle that is always available to an authenticated user.
PUZZLE = "jump-the-queue"
# Correctness is irrelevant here: we assert the *shape* of the play result, so
# trivial code that merely compiles is enough.
TRIVIAL_PYTHON = 'print("")'

ENV_ALLOW_SUBMIT = "CODINGAME_ALLOW_SUBMIT_TEST"

# A known-correct solution (TypeScript) for jump-the-queue: re-submitting it to
# an already-solved puzzle keeps the score at 100, so the submit test is
# idempotent -- but it still really submits, hence the explicit opt-in gate.
CORRECT_TYPESCRIPT = """\
const [g] = readline().split(" ").map(Number)

const groupOf = new Map<number, number>()
for (let i = 0; i < g; i++) {
  for (const id of readline().split(" ").map(Number)) {
    groupOf.set(id, i)
  }
}

const queue: number[] = []
const output: number[] = []

for (const event of readline().split(" ").map(Number)) {
  if (event === -1) {
    output.push(queue.shift()!)
    continue
  }
  const group = groupOf.get(event)
  let insertAt = queue.length
  if (group !== undefined) {
    const first = queue.findIndex((id) => groupOf.get(id) === group)
    if (first !== -1) {
      let i = first
      while (i + 1 < queue.length && groupOf.get(queue[i + 1]) === group) i++
      insertAt = i + 1
    }
  }
  queue.splice(insertAt, 0, event)
}

console.log(output.join("\\n"))
"""


async def test_run_tests_returns_shaped_per_case_results(client):
    """Running a puzzle's visible tests yields one shaped result per case."""
    results = await client.run_tests(PUZZLE, "Python3", TRIVIAL_PYTHON)
    assert results, "expected at least one test-case result"
    first = results[0]
    assert first.index is not None
    # Each case carries a comparison whose success is a boolean.
    assert first.comparison is not None
    assert isinstance(first.comparison.get("success"), bool)


@pytest.mark.skipif(
    not os.environ.get(ENV_ALLOW_SUBMIT, "").strip(),
    reason=f"{ENV_ALLOW_SUBMIT} not set; skipping the real submission test.",
)
async def test_submit_returns_graded_report(client):
    """Submitting polls until the report carries the per-validator grading."""
    report = await client.submit(PUZZLE, "TypeScript", CORRECT_TYPESCRIPT)
    assert report.score is not None
    assert report.validators, "expected per-validator results"
    first = report.validators[0]
    assert first.name
    assert isinstance(first.success, bool)
