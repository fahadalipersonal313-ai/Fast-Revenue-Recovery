"""Tests for the Free-tier AI-refine monthly cap (gating.py + memory counter).

Free users get FREE_AI_REFINE_LIMIT_PER_MONTH interactive AI refines per month
(fine-tune + tone variants each count as 1); Pro is unlimited. The counter is a
per-tenant month->count map in the settings KV table."""

from __future__ import annotations

from src import gating
from src.auth import User


def _free() -> User:
    return User(id=1, email="f@x.com", tenant_slug="f", company_name="F", tier="free")


def _pro() -> User:
    return User(id=2, email="p@x.com", tenant_slug="p", company_name="P", tier="pro",
                pro_until=None)  # lifetime pro


# --- memory counter --------------------------------------------------------
def test_counter_starts_at_zero_and_increments(memory):
    assert memory.ai_refine_usage_this_month() == 0
    assert memory.increment_ai_refine_usage() == 1
    assert memory.increment_ai_refine_usage() == 2
    assert memory.ai_refine_usage_this_month() == 2


def test_counter_is_month_scoped(memory, monkeypatch):
    memory.increment_ai_refine_usage()
    # Pretend the month rolled over — a new month key => fresh count.
    monkeypatch.setattr(type(memory), "_current_month_key",
                        staticmethod(lambda: "2099-01"))
    assert memory.ai_refine_usage_this_month() == 0


# --- gating: Free is capped, Pro is unlimited ------------------------------
def test_free_allowed_until_cap(memory):
    user = _free()
    for _ in range(gating.FREE_AI_REFINE_LIMIT_PER_MONTH):
        assert gating.ai_refine_allowed(user, memory) is True
        gating.record_ai_refine(user, memory)
    # Now at the cap.
    assert gating.ai_refine_allowed(user, memory) is False
    assert gating.ai_refines_remaining(user, memory) == 0


def test_free_remaining_counts_down(memory):
    user = _free()
    assert gating.ai_refines_remaining(user, memory) == gating.FREE_AI_REFINE_LIMIT_PER_MONTH
    gating.record_ai_refine(user, memory)
    assert gating.ai_refines_remaining(user, memory) == \
        gating.FREE_AI_REFINE_LIMIT_PER_MONTH - 1


def test_pro_is_unlimited_and_not_counted(memory):
    user = _pro()
    assert gating.ai_refines_remaining(user, memory) is None
    # Recording for a Pro user is a no-op — the Free counter never moves.
    for _ in range(gating.FREE_AI_REFINE_LIMIT_PER_MONTH + 5):
        assert gating.ai_refine_allowed(user, memory) is True
        gating.record_ai_refine(user, memory)
    assert memory.ai_refine_usage_this_month() == 0
    assert gating.ai_refine_allowed(user, memory) is True
