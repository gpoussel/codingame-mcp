"""Unit tests for the write-enable flag (pure, no network)."""

from __future__ import annotations

import pytest

from codingame_mcp.config import ENV_ENABLE_WRITES, writes_enabled


def test_writes_disabled_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_ENABLE_WRITES, raising=False)
    assert writes_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "  yes  "])
def test_writes_enabled_for_truthy_values(monkeypatch, value):
    monkeypatch.setenv(ENV_ENABLE_WRITES, value)
    assert writes_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_writes_disabled_for_falsy_values(monkeypatch, value):
    monkeypatch.setenv(ENV_ENABLE_WRITES, value)
    assert writes_enabled() is False
