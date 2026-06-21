"""Tests for supervisor safety / approval decisions."""

from datetime import date, timedelta

from src.invoice_agent import analyze_invoice
from src.quote_agent import analyze_quote
from src.supervisor_agent import build_daily_plan, review

REF = date(2026, 6, 14)


def test_disputed_invoice_blocked(settings):
    rec = {"customer_name": "C", "invoice_number": "3",
           "due_date": (REF - timedelta(days=15)).isoformat(),
           "amount_due": 4300, "payment_status": "unpaid", "dispute_status": "Yes"}
    d = analyze_invoice(rec, settings, REF)
    sd = review(d, settings)
    assert "disputed invoice action" in sd.blocked_actions
    assert sd.requires_approval is True


def test_final_escalation_never_auto_approved(settings):
    rec = {"customer_name": "E", "invoice_number": "5",
           "due_date": (REF - timedelta(days=90)).isoformat(),
           "amount_due": 6400, "payment_status": "unpaid"}
    d = analyze_invoice(rec, settings, REF)
    sd = review(d, settings)
    assert "automatic final escalation" in sd.blocked_actions
    assert sd.requires_approval is True


def test_high_value_flagged(settings):
    rec = {"customer_name": "H", "invoice_number": "9",
           "due_date": (REF - timedelta(days=10)).isoformat(),
           "amount_due": 9000, "payment_status": "unpaid"}
    d = analyze_invoice(rec, settings, REF)
    sd = review(d, settings)
    assert "high value sensitive communication" in sd.blocked_actions


def test_daily_plan_sorted_by_priority(settings):
    low = analyze_invoice({"customer_name": "Low", "invoice_number": "1",
                           "due_date": (REF - timedelta(days=3)).isoformat(),
                           "amount_due": 200, "payment_status": "unpaid"}, settings, REF)
    high = analyze_invoice({"customer_name": "High", "invoice_number": "2",
                            "due_date": (REF - timedelta(days=80)).isoformat(),
                            "amount_due": 9000, "payment_status": "unpaid"}, settings, REF)
    plan = build_daily_plan([low, high], settings)
    assert plan[0].name == "High"
