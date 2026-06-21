"""Tests for invoice risk, stage, missed promise and dispute handling."""

from datetime import date, timedelta

from src.invoice_agent import analyze_invoice, base_risk
from src.models import InvoiceStage, RiskLevel


REF = date(2026, 6, 14)


def _due(days_overdue: int) -> str:
    return (REF - timedelta(days=days_overdue)).isoformat()


def test_invoice_risk_level_thresholds():
    assert base_risk(0) == RiskLevel.NONE
    assert base_risk(5) == RiskLevel.LOW
    assert base_risk(20) == RiskLevel.MEDIUM
    assert base_risk(45) == RiskLevel.HIGH
    assert base_risk(90) == RiskLevel.CRITICAL


def test_recovery_stage_selection(settings):
    rec = {"customer_name": "A", "invoice_number": "1", "due_date": _due(5),
           "amount_due": 500, "payment_status": "unpaid"}
    d = analyze_invoice(rec, settings, reference_date=REF)
    assert d.stage == InvoiceStage.COURTESY_REMINDER
    assert d.days_overdue == 5

    rec["due_date"] = _due(20)
    assert analyze_invoice(rec, settings, REF).stage == InvoiceStage.STANDARD_REMINDER

    rec["due_date"] = _due(45)
    assert analyze_invoice(rec, settings, REF).stage == InvoiceStage.FIRM_REMINDER

    rec["due_date"] = _due(90)
    assert analyze_invoice(rec, settings, REF).stage == InvoiceStage.FINAL_INTERNAL_ESCALATION


def test_missed_promise_detection(settings):
    rec = {"customer_name": "B", "invoice_number": "2", "due_date": _due(30),
           "amount_due": 1000, "payment_status": "unpaid",
           "promised_payment_date": (REF - timedelta(days=5)).isoformat()}
    d = analyze_invoice(rec, settings, REF)
    assert d.missed_promise is True
    assert d.stage == InvoiceStage.MISSED_PROMISE_FOLLOW_UP


def test_dispute_safety_handling(settings):
    rec = {"customer_name": "C", "invoice_number": "3", "due_date": _due(15),
           "amount_due": 4300, "payment_status": "unpaid", "dispute_status": "Yes"}
    d = analyze_invoice(rec, settings, REF)
    assert d.is_disputed is True
    assert d.stage == InvoiceStage.HUMAN_REVIEW
    assert d.needs_human_review is True


def test_high_value_needs_review(settings):
    rec = {"customer_name": "D", "invoice_number": "4", "due_date": _due(10),
           "amount_due": 9000, "payment_status": "unpaid"}
    d = analyze_invoice(rec, settings, REF)
    assert d.needs_human_review is True


def test_paid_invoice_no_action(settings):
    rec = {"customer_name": "E", "invoice_number": "5", "due_date": _due(10),
           "amount_due": 0, "payment_status": "Paid"}
    d = analyze_invoice(rec, settings, REF)
    assert d.is_overdue is False
    assert d.stage == InvoiceStage.NOT_DUE
    # A thank-you message is offered.
    assert d.messages
