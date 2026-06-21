"""Invoice → recovery pipeline: scheduled reminders feed plan + approval queue."""

from __future__ import annotations

from datetime import date, timedelta

from src import bulk_invoice as bulk
from src import invoice_generator as ig
from src.invoice_agent import analyze_invoice
from src.approval_engine import analyze_and_queue, queue_counts
from src.models import InvoiceStage, Priority
from src.scheduler import load_active_records


def _rec(**kw):
    base = {"customer_name": "Acme", "invoice_number": "INV-1", "amount_due": 500,
            "payment_status": "unpaid"}
    base.update(kw)
    return base


# --- invoice agent honours scheduled_reminder_date -------------------------
def test_future_reminder_keeps_invoice_not_due(settings):
    rec = _rec(due_date="2099-01-01",
               scheduled_reminder_date=(date.today() + timedelta(days=10)).isoformat())
    d = analyze_invoice(rec, settings)
    assert d.stage == InvoiceStage.NOT_DUE
    assert not d.messages  # nothing to send yet


def test_reached_reminder_fires_even_before_due(settings):
    rec = _rec(due_date="2099-01-01",
               scheduled_reminder_date=date.today().isoformat())
    d = analyze_invoice(rec, settings)
    assert d.stage != InvoiceStage.NOT_DUE
    assert d.messages                      # a reminder message was drafted
    assert any("reminder" in r.lower() for r in d.reasons)


def test_paid_invoice_ignores_reminder(settings):
    rec = _rec(amount_due=0, payment_status="paid",
               scheduled_reminder_date=date.today().isoformat())
    d = analyze_invoice(rec, settings)
    # Paid → no recovery: stays NOT_DUE at NONE priority (a thank-you, not a chase).
    assert d.stage == InvoiceStage.NOT_DUE
    assert d.priority == Priority.NONE


# --- to_record -------------------------------------------------------------
def test_to_record_shape_and_amount():
    data = ig.InvoiceData(
        from_company="Me", customer_name="Acme", customer_email="a@b.com",
        invoice_number="INV-9", issue_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
        currency_symbol="$", tax_rate_percent=10.0,
        line_items=[ig.LineItem("Work", 1, 100.0)],
    )
    rec = ig.to_record(data, scheduled_reminder_date=date(2026, 2, 8))
    assert rec["customer_name"] == "Acme"
    assert rec["invoice_number"] == "INV-9"
    assert rec["amount_due"] == 110.0           # total incl 10% tax
    assert rec["due_date"] == "2026-02-01"
    assert rec["email"] == "a@b.com"
    assert rec["scheduled_reminder_date"] == "2026-02-08"


def test_to_record_blank_reminder_is_empty():
    data = ig.InvoiceData(from_company="Me", customer_name="Acme",
                          line_items=[ig.LineItem("Work", 1, 50.0)])
    assert ig.to_record(data)["scheduled_reminder_date"] == ""


# --- bulk per-invoice reminder date ----------------------------------------
def test_reminder_date_uses_due_plus_days():
    data = ig.InvoiceData(from_company="Me", customer_name="Acme",
                          due_date=date(2026, 3, 1),
                          line_items=[ig.LineItem("x", 1, 10)])
    assert bulk.reminder_date_for(data, 7) == date(2026, 3, 8)


def test_reminder_date_falls_back_to_issue_then_today():
    only_issue = ig.InvoiceData(from_company="Me", customer_name="Acme",
                                issue_date=date(2026, 3, 1),
                                line_items=[ig.LineItem("x", 1, 10)])
    assert bulk.reminder_date_for(only_issue, 5) == date(2026, 3, 6)
    neither = ig.InvoiceData(from_company="Me", customer_name="Acme",
                             line_items=[ig.LineItem("x", 1, 10)])
    assert bulk.reminder_date_for(neither, 0) == date.today()


# --- integration: generated invoice joins records + queue ------------------
def test_generated_invoice_is_tracked_and_queued(memory, settings):
    data = ig.InvoiceData(
        from_company="Test Co", customer_name="Acme", customer_email="a@b.com",
        invoice_number="INV-77", due_date=date(2099, 1, 1),
        line_items=[ig.LineItem("Service", 1, 300.0)],
    )
    # Reminder due today → should enqueue an approval immediately.
    rec = ig.to_record(data, scheduled_reminder_date=date.today())
    analyze_and_queue(memory, settings, {"invoice": [rec]})

    active = load_active_records(memory)
    assert any(r.get("invoice_number") == "INV-77" for r in active["invoice"])
    assert queue_counts(memory).get("pending", 0) >= 1


def test_tracked_invoice_without_reminder_is_not_queued(memory, settings):
    data = ig.InvoiceData(
        from_company="Test Co", customer_name="Beta", invoice_number="INV-88",
        due_date=date(2099, 1, 1),  # far future, not overdue
        line_items=[ig.LineItem("Service", 1, 120.0)],
    )
    rec = ig.to_record(data)  # no reminder
    analyze_and_queue(memory, settings, {"invoice": [rec]})
    active = load_active_records(memory)
    assert any(r.get("invoice_number") == "INV-88" for r in active["invoice"])
    assert queue_counts(memory).get("pending", 0) == 0  # tracked but not queued
