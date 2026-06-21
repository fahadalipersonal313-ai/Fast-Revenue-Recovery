"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the project root is importable when pytest is run from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings  # noqa: E402
from src.memory import AgentMemory  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    # AI explicitly off so tests exercise the deterministic path.
    return Settings(ai_enabled=False, high_value_threshold=5000.0,
                    company_name="Test Co", currency_symbol="$")


@pytest.fixture
def memory(tmp_path) -> AgentMemory:
    return AgentMemory(path=tmp_path / "test.db")
