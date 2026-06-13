"""The write tools are exposed only when the write flag is enabled."""

from __future__ import annotations

import importlib

from codingame_mcp.config import ENV_ENABLE_WRITES

WRITE_TOOLS = {"run_puzzle_tests", "submit_puzzle_solution", "claim_puzzle_labels"}


async def _tool_names(monkeypatch, *, enabled: bool) -> set[str]:
    """Reload the server with the flag set/unset and return its tool names."""
    if enabled:
        monkeypatch.setenv(ENV_ENABLE_WRITES, "1")
    else:
        monkeypatch.delenv(ENV_ENABLE_WRITES, raising=False)
    import codingame_mcp.server as server

    importlib.reload(server)
    tools = await server.mcp.list_tools()
    return {t.name for t in tools}


async def test_write_tools_hidden_when_disabled(monkeypatch):
    names = await _tool_names(monkeypatch, enabled=False)
    assert not (WRITE_TOOLS & names), "write tools must be hidden when flag is off"
    # Read tools stay available regardless of the flag.
    assert "list_puzzles" in names


async def test_write_tools_present_when_enabled(monkeypatch):
    names = await _tool_names(monkeypatch, enabled=True)
    assert WRITE_TOOLS <= names, "write tools must be exposed when flag is on"
