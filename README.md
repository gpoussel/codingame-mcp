# codingame-mcp

A read-only [MCP](https://modelcontextprotocol.io) server for
[CodinGame](https://www.codingame.com), built with the
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (`MCPServer`).

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
| `get_user_progress(handle, summary=True, fields=None, include_rank_history=False)` | A user's CodinGame points / progress. Summarized by default (total points, rank, per-category breakdown); the raw record is ~357k chars, ~99% of it `rankHistory` + `xpThresholds`. |
| `list_puzzles(level=None, type=None, solved=None, limit=50, offset=0, fields=None)` | Puzzles with the authenticated user's progress (`validatorScore` 0-100, plus a derived `solved`), filtered and paged. `total` counts every match, not just the page — so `solved=True, limit=0` gives a tally in one call. |
| `get_puzzle(pretty_id, include_statement=False, include_viewer=False, fields=None)` | A single puzzle's metadata (topics, xp, type, contributor) + progress. The HTML statement and the `viewer` JS game bundle (up to 240k chars on multi/optim puzzles) are both opt-in. |
| `get_puzzle_tests(pretty_id)` | Solving material: statement, languages, code stub, and test cases with inlined I/O. |
| `get_puzzle_leaderboard(pretty_id, language=None, limit=20, offset=0)` | A puzzle's leaderboard, optionally for one language: rank within the list, global rank, pseudo, language, score, `criteriaScore` (bytes on code golf) and submission date, plus the authenticated user's entry as `me`. CodinGame caps a leaderboard at 1000 entries (`capped`). |
| `recommend_next_puzzles(pretty_id)` | The puzzles CodinGame suggests tackling next. |
| `get_account_summary()` | Navbar counters: unseen notifications, lootable quests, new contributions/events. |
| `get_arena_status(pretty_id, neighbours=5)` | Multiplayer: your league (Wood 3 … Legend), room rank, score, submission progress (`percentage`/`inProgress`), the league boss and the agents ranked around you (their `agentId`s are valid opponents). |
| `get_arena_battles(pretty_id, limit=20)` | Multiplayer: your agent's last arena battles with opponents, your seat, outcome (win/loss/draw) and seed, plus the tally. |
| `get_game_replay(game_id, seat=None, offset=0, limit=100, include_view=False)` | A game's turn-by-turn log (stdout, stderr, summary per frame), paged and optionally for one seat. |

Write tools (exposed **only** when `CODINGAME_ENABLE_WRITES` is truthy — see
[Enabling writes](#enabling-writes)):

| Tool | Description |
| --- | --- |
| `run_puzzle_tests(pretty_id, language, code \| code_file)` | Run a puzzle's visible test cases against your code. Does **not** affect your score. |
| `submit_puzzle_solution(pretty_id, language, code \| code_file)` | Submit for official grading. **Affects your score/ranking**; returns the per-validator result. |
| `claim_puzzle_labels(pretty_id)` | Claim a puzzle's labels (topics) onto your profile. **Changes your profile**; returns the labels claimed. |
| `play_arena_games(pretty_id, language, code \| code_file, opponents=None, games=1, seed=None, rotate_seats=True, stderr_tail=0)` | Multiplayer: play IDE games against the boss (`"boss"`), yourself (`"self"`) or arena agents (`agentId`), rotating seats. Returns the win/loss/draw tally and per-game outcome, seed and events (timeouts, invalid moves). Does **not** affect your ranking. |
| `submit_arena_bot(pretty_id, language, code \| code_file, wait_seconds=0)` | Multiplayer: submit to the arena. **Replaces your ranked agent**; returns its ranking (optionally after waiting for its ranking games). |

> `handle` is the **public handle** (the long hex id in profile URLs), not the
> display pseudo. `pretty_id` is the slug from a puzzle's training URL.
> `language` is a `programmingLanguageId` (e.g. `Python3`, `TypeScript`, `Java`)
> from `get_puzzle_tests`. Write tools take either `code` or `code_file`, an
> absolute path to a local source file whose extension gives the language
> when `language` is omitted.

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

The tests that perform a **real** profile-changing write are opt-in and skipped
unless you set their env var: `CODINGAME_ALLOW_SUBMIT_TEST` (submits a solution)
and `CODINGAME_ALLOW_CLAIM_TEST` (claims a puzzle's labels). `run_puzzle_tests`
is exercised by default since it doesn't affect your score.

## Project layout

```
src/codingame_mcp/
  config.py      # read CODINGAME_REMEMBER_ME
  endpoints.py   # CodinGame service paths (single source of truth)
  client.py      # async httpx client: cookie, request(), typed methods
  models.py      # lenient pydantic models
  server.py      # MCPServer instance + tools
tests/           # live tests, cookie-gated
```

## Extending

Adding a capability (e.g. challenges) is a three-step pattern: add the service
path to `endpoints.py`, a model to `models.py`, a client method to `client.py`,
and a `@mcp.tool()` in `server.py`.
