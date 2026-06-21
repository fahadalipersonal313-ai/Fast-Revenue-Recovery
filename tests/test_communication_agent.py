"""Tests for message generation (template/rules mode)."""

from src.communication_agent import build_context, generate_message, generate_pair
from src.models import MessageChannel, MessageKind


def test_message_generation_fills_context(settings):
    ctx = build_context(customer="Acme", settings=settings, amount=1200,
                        days_overdue=10, reference="INV-1")
    msg = generate_message(MessageKind.STANDARD_REMINDER, MessageChannel.WHATSAPP,
                           ctx, settings)
    assert "Acme" in msg.body
    assert "INV-1" in msg.body
    assert "10" in msg.body
    assert msg.ai_improved is False  # AI disabled


def test_no_threats_or_legal_language(settings):
    ctx = build_context(customer="Acme", settings=settings, amount=9999,
                        days_overdue=90, reference="INV-9")
    for kind in MessageKind:
        for msg in generate_pair(kind, ctx, settings):
            lowered = msg.body.lower()
            for bad in ["legal action", "lawsuit", "sue you", "take you to court",
                        "or else", "debt collector", "late fee"]:
                assert bad not in lowered


def test_escalation_is_email_only_and_internal(settings):
    ctx = build_context(customer="Acme", settings=settings, amount=9999,
                        days_overdue=90, reference="INV-9")
    msgs = generate_pair(MessageKind.FINAL_ESCALATION_DRAFT, ctx, settings)
    assert len(msgs) == 1
    assert msgs[0].channel == MessageChannel.EMAIL
    assert "internal" in msgs[0].body.lower()
