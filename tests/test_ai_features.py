"""Tests for the AI-assisted features: tone variants and reply-intent detection.

The AI calls themselves are not exercised here (no network / no key in tests).
We verify:

* The public helpers fail safe — they return None when AI is unavailable, and
  parse/sanitise model output correctly when we feed it a known response.
* The deterministic reply-action mapping (the safety boundary) is correct and
  independent of any AI.
"""

from __future__ import annotations

import src.ai_helper as ai
from src.ai_helper import (
    REPLY_INTENTS,
    TONE_VARIANTS,
    classify_reply,
    improve_message,
    message_tone_variants,
)
from src.reply_actions import describe_classification, suggest_next_step


# ---------------------------------------------------------------------------
# Fail-safe behaviour when AI is off
# ---------------------------------------------------------------------------
def test_tone_variants_none_when_ai_disabled(settings):
    assert message_tone_variants("Please pay invoice 5.", settings) is None


def test_classify_reply_none_when_ai_disabled(settings):
    assert classify_reply("I already paid this last week.", settings) is None


def test_tone_variants_none_for_empty_text(settings):
    assert message_tone_variants("   ", settings) is None


# ---------------------------------------------------------------------------
# Output parsing (AI forced "available" + a stubbed completion)
# ---------------------------------------------------------------------------
def _force_ai(monkeypatch, fake_raw):
    monkeypatch.setattr(ai, "ai_available", lambda settings: True)
    monkeypatch.setattr(ai, "_complete", lambda system, prompt, settings, max_tokens: fake_raw)


def test_tone_variants_parsed(monkeypatch, settings):
    _force_ai(monkeypatch,
              '{"gentle": "Hi, gentle nudge.", "neutral": "Reminder.", "firm": "Please pay now."}')
    out = message_tone_variants("Please pay invoice 5.", settings)
    assert out == {"gentle": "Hi, gentle nudge.", "neutral": "Reminder.", "firm": "Please pay now."}
    assert list(out.keys()) == TONE_VARIANTS


def test_tone_variants_tolerates_extra_prose(monkeypatch, settings):
    raw = 'Sure! Here you go:\n{"gentle":"g","neutral":"n","firm":"f"}\nHope that helps.'
    _force_ai(monkeypatch, raw)
    out = message_tone_variants("x", settings)
    assert out == {"gentle": "g", "neutral": "n", "firm": "f"}


def test_tone_variants_none_on_garbage(monkeypatch, settings):
    _force_ai(monkeypatch, "not json at all")
    assert message_tone_variants("x", settings) is None


def test_classify_reply_parsed_and_clamped(monkeypatch, settings):
    _force_ai(monkeypatch,
              '{"intent":"promise_to_pay","confidence":1.7,'
              '"promised_date":"2026-07-01","summary":"Will pay July 1."}')
    out = classify_reply("I'll pay on July 1.", settings)
    assert out["intent"] == "promise_to_pay"
    assert out["confidence"] == 1.0  # clamped to [0,1]
    assert out["promised_date"] == "2026-07-01"
    assert out["summary"] == "Will pay July 1."


def test_classify_reply_unknown_intent_becomes_other(monkeypatch, settings):
    _force_ai(monkeypatch, '{"intent":"angry_rant","confidence":0.5,"promised_date":null,"summary":"x"}')
    out = classify_reply("...", settings)
    assert out["intent"] == "other"
    assert out["promised_date"] is None


# ---------------------------------------------------------------------------
# Fine-tune (improve_message) — fail-safe + optional user instruction
# ---------------------------------------------------------------------------
def test_improve_message_none_when_ai_disabled(settings):
    assert improve_message("Please pay invoice 5.", "polite", settings) is None


def test_improve_message_none_for_empty_text(settings):
    assert improve_message("   ", "polite", settings) is None


def test_improve_message_returns_refined_text(monkeypatch, settings):
    # Real provider backends strip; the stub returns whatever _complete gives,
    # so improve_message is a straight pass-through of the model text.
    _force_ai(monkeypatch, "Here is a warmer reminder.")
    out = improve_message("Pay now.", "warm", settings)
    assert out == "Here is a warmer reminder."


def test_improve_message_passes_instruction_into_prompt(monkeypatch, settings):
    captured = {}

    def _fake_complete(system, prompt, settings, max_tokens):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(ai, "ai_available", lambda settings: True)
    monkeypatch.setattr(ai, "_complete", _fake_complete)

    improve_message("Pay invoice 5.", "polite", settings,
                    instruction="make it shorter")
    assert "make it shorter" in captured["prompt"]
    # The base message is still present in the prompt.
    assert "Pay invoice 5." in captured["prompt"]


def test_improve_message_blank_instruction_adds_nothing(monkeypatch, settings):
    captured = {}

    def _fake_complete(system, prompt, settings, max_tokens):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(ai, "ai_available", lambda settings: True)
    monkeypatch.setattr(ai, "_complete", _fake_complete)

    improve_message("Pay invoice 5.", "polite", settings, instruction="   ")
    assert "Extra instruction" not in captured["prompt"]


# ---------------------------------------------------------------------------
# Deterministic safety boundary (no AI involved)
# ---------------------------------------------------------------------------
def test_every_intent_has_action():
    for intent in REPLY_INTENTS:
        advice = suggest_next_step(intent)
        assert advice["action"]
        assert isinstance(advice["needs_human"], bool)


def test_disputes_and_already_paid_need_human():
    assert suggest_next_step("dispute")["needs_human"] is True
    assert suggest_next_step("already_paid")["needs_human"] is True


def test_promise_to_pay_is_positive_and_self_serve():
    advice = suggest_next_step("promise_to_pay")
    assert advice["needs_human"] is False
    assert advice["tone"] == "positive"


def test_describe_classification_handles_none():
    advice = describe_classification(None)
    assert advice["intent"] == "other"
    assert advice["needs_human"] is True
    assert advice["confidence"] == 0.0
