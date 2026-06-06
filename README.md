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

All tools are read-only:

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

> `handle` is the **public handle** (the long hex id in profile URLs), not the
> display pseudo. `pretty_id` is the slug from a puzzle's training URL.

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

Register the server from the project directory with the `claude mcp` CLI. The
`--` separates Claude's flags from the launch command, `--env` injects the
cookie, and `--scope` chooses where the config lives:

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

> Because `uv run` resolves the project from the working directory, add the
> server from this repo's root (or use an absolute path to `uv`).

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
