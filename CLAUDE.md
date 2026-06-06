# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A read-only [MCP](https://modelcontextprotocol.io) server (FastMCP) exposing
[CodinGame](https://www.codingame.com) data. CodinGame has **no public API**:
this server calls its undocumented internal JSON API and authenticates with a
browser `rememberMe` cookie.

## Commands

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev                 # install (incl. pytest, pytest-asyncio)
uv run codingame-mcp                # run the stdio server
uv run pytest                       # full suite
uv run pytest tests/test_puzzles.py::test_list_puzzles_non_empty   # single test
```

Tests run **against the live CodinGame site** and require a valid cookie in
`CODINGAME_REMEMBER_ME`; without it the whole suite is **skipped** (see
`tests/conftest.py`). The cookie is the `rememberMe` value from a logged-in
codingame.com browser session.

### Browser UI for manual testing

Use the MCP Inspector against the launch command — **not** `mcp dev server.py`,
which imports the file by path and breaks the package-relative imports:

```bash
npx @modelcontextprotocol/inspector uv run codingame-mcp
```

## API model

Every CodinGame call is an HTTP `POST` to `/services/{Service}/{func}` whose
body is a **JSON array of positional arguments**. Conventions that matter:

- A wrong argument **count** returns `Service not found: service.func(N)` — the
  fastest signal that an endpoint's signature changed.
- Errors come back as a JSON envelope (e.g. `{"id": -3, "message": ...}`),
  sometimes with a **200** status. `CodinGameClient.request` detects this and
  raises `CodinGameError`.
- Auth is the `rememberMe` cookie only; it is read from the environment and is
  never a tool argument, so it can't leak into tool-call transcripts.

## Architecture: the four-layer pattern

Adding any capability touches the same four files, in order:

1. **`endpoints.py`** — every service path as a named `(Service, func)` tuple,
   the single source of truth. The trailing comment records the **argument
   count** (verified against the live API). Tests assert against these.
2. **`models.py`** — pydantic models with `extra="allow"` (`CGModel` base):
   payloads can gain fields without breaking parsing, while *declared* fields
   document the dependency surface that the live tests guard.
3. **`client.py`** — `CodinGameClient`, an async httpx client holding the cookie
   and a lazily-resolved authenticated user id. Typed methods wrap `_call`.
4. **`server.py`** — `@mcp.tool()` functions over a single lazily-built,
   shared, login-verified `CodinGameClient`.

## Non-obvious behaviors

- **Puzzle listing is two calls.** `findAllMinimalProgress` returns only ids +
  progress (no `prettyId`/`title`), so `list_puzzles` enumerates ids there and
  hydrates them via `findProgressByIds [ids, userId, 1]` (the trailing `1` is
  required). `get_puzzle` uses `findProgressByPrettyId`, which alone carries the
  detail fields (`statement`, `topics`, ...) — these are `None` on list entries.
- **`server.py` is a presentation layer.** The `list_puzzles` tool trims
  noise/detail-only fields (`_LIST_PUZZLE_HIDDEN_FIELDS`) from each entry; the
  client method still returns the full typed record. Keep client = full
  fidelity, tools = shaped-for-the-LLM.
- **Test cases come from a test session.** `get_puzzle_tests` calls
  `generateSessionFromPuzzlePrettyId` then `startTestSession`; the visible test
  cases reference I/O as binary blobs, fetched as plain text from
  `static.codingame.com/servlet/fileservlet?id=<binaryId>` (no auth needed).

## Tests philosophy

Live tests assert **structural invariants** (which fields/types exist), not
values, so they fail loudly when CodinGame changes its API but tolerate normal
data churn. When adding an endpoint, add a test that asserts the fields the code
relies on actually come back.
