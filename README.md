# codingame-mcp

A read-only [MCP](https://modelcontextprotocol.io) server for
[CodinGame](https://www.codingame.com), built with
[FastMCP](https://github.com/modelcontextprotocol/python-sdk).

CodinGame has no public API and no longer supports username/password login, so
this server talks to its **undocumented** internal JSON API
(`https://www.codingame.com/services/{Service}/{func}`) and authenticates with
the **`rememberMe` cookie** copied from a logged-in browser session.

> ⚠️ The CodinGame API is undocumented and can change without notice. The test
> suite runs **against the live site** specifically so those changes are caught
> early.

## Tools

Read-only tools (always available):

| Tool | Description |
| --- | --- |
| `whoami` | The authenticated user (also verifies the cookie). |
| `get_user(handle)` | A user's public details by public handle. |
| `get_user_progress(handle)` | A user's CodinGame points / progress. |
| `list_puzzles()` | All puzzles with the authenticated user's progress. |
| `get_puzzle(pretty_id)` | A single puzzle's detail (incl. statement, topics, xp) + progress. |
| `get_puzzle_tests(pretty_id)` | Solving material: statement, languages, code stub, and test cases with inlined I/O. |
| `recommend_next_puzzles(pretty_id)` | The puzzles CodinGame suggests tackling next. |
| `get_account_summary()` | Navbar counters: unseen notifications, lootable quests, new contributions/events. |

Write tools (exposed **only** when `CODINGAME_ENABLE_WRITES` is truthy — see
[Enabling writes](#enabling-writes)):

| Tool | Description |
| --- | --- |
| `run_puzzle_tests(pretty_id, language, code)` | Run a puzzle's visible test cases against your code. Does **not** affect your score. |
| `submit_puzzle_solution(pretty_id, language, code)` | Submit for official grading. **Affects your score/ranking**; returns the per-validator result. |

> `handle` is the **public handle** (the long hex id in profile URLs), not the
> display pseudo. `pretty_id` is the slug from a puzzle's training URL.
> `language` is a `programmingLanguageId` (e.g. `Python3`, `TypeScript`, `Java`)
> from `get_puzzle_tests`.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
```

### Get your cookie

1. Log in at <https://www.codingame.com>.
2. Open DevTools (F12) → **Application** (Chrome) / **Storage** (Firefox) →
   Cookies → `https://www.codingame.com`.
3. Copy the **value** of the `rememberMe` cookie.

Set it as an environment variable (see `.env.example`):

```bash
export CODINGAME_REMEMBER_ME="<your-rememberMe-cookie-value>"
```

### Enabling writes

By default the server is **read-only**: the write tools are not even registered,
so an MCP client never sees them. To expose `run_puzzle_tests` and
`submit_puzzle_solution`, set a truthy `CODINGAME_ENABLE_WRITES`
(`1`/`true`/`yes`/`on`):

```bash
export CODINGAME_ENABLE_WRITES=1
```

> ⚠️ `submit_puzzle_solution` performs a **real submission** that affects your
> CodinGame score and ranking. `run_puzzle_tests` only runs the visible test
> cases and is safe.

## Run

```bash
uv run codingame-mcp          # stdio server
# or
uv run python -m codingame_mcp
```

Inspect interactively with the MCP Inspector:

```bash
uv run mcp dev src/codingame_mcp/server.py
```

### Use with Claude Code

Register the server with the `claude mcp` CLI. The `--` separates Claude's flags
from the launch command, `--env` injects the cookie, and `--scope` chooses where
the config lives.

**To use it from any repo** (the common case — you run Claude Code in another
project and want CodinGame tools available there), register it at `user` scope
and point `uv` at this checkout with `--directory` so the launch works
regardless of the working directory:

```bash
claude mcp add codingame \
  --scope user \
  --env CODINGAME_REMEMBER_ME="<your-rememberMe-cookie-value>" \
  -- uv run --directory /absolute/path/to/codingame-mcp codingame-mcp
```

If you only want it inside this repo, drop `--directory` and use `--scope local`
while adding it from this directory:

```bash
claude mcp add codingame \
  --scope local \
  --env CODINGAME_REMEMBER_ME="<your-rememberMe-cookie-value>" \
  -- uv run codingame-mcp
```

Scopes: `local` (default, private to you in this project), `user` (available
across all your projects), or `project` (writes a checked-in `.mcp.json` shared
with your team — **do not** put the cookie there; use `${CODINGAME_REMEMBER_ME}`
and set the variable in your environment instead).

Manage it with `claude mcp list`, `claude mcp get codingame`, and
`claude mcp remove codingame`.

### Use with Claude Desktop

Add the server to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "codingame": {
      "command": "uv",
      "args": ["run", "codingame-mcp"],
      "env": { "CODINGAME_REMEMBER_ME": "<your-rememberMe-cookie-value>" }
    }
  }
}
```

## Tests (live)

The tests hit the real API and **require a valid cookie**. Without
`CODINGAME_REMEMBER_ME` set, the whole suite is skipped.

```bash
export CODINGAME_REMEMBER_ME="<your-rememberMe-cookie-value>"
uv run pytest -v
```

They assert on structural invariants (which fields/types exist), so they fail
loudly when CodinGame changes its API but tolerate normal data churn.

## Project layout

```
src/codingame_mcp/
  config.py      # read CODINGAME_REMEMBER_ME
  endpoints.py   # CodinGame service paths (single source of truth)
  client.py      # async httpx client: cookie, request(), typed methods
  models.py      # lenient pydantic models
  server.py      # FastMCP instance + tools
tests/           # live tests, cookie-gated
```

## Extending

Adding a capability (e.g. challenges) is a three-step pattern: add the service
path to `endpoints.py`, a model to `models.py`, a client method to `client.py`,
and a `@mcp.tool()` in `server.py`.
