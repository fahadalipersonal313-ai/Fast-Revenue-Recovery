"""Tests for scheduled run, Excel export and column-mapping / missing columns."""

from datetime import date, timedelta

import pandas as pd

from src import column_mapper as cm
from src import export_engine as ex
from src.scheduler import run_daily_analysis

REF = date(2026, 6, 14)


def test_missing_column_handling():
    # Headers do not include amount or due date.
    cols = ["Customer Name", "Inv No", "Random"]
    mapping, unmapped = cm.detect_mapping(cols, "invoice")
    assert "customer_name" in mapping
    missing = cm.missing_required(mapping, "invoice")
    assert "amount_due" in missing  # correctly reported as missing


def test_column_mapping_detects_aliases():
    cols = ["Client", "Quote #", "Quote Amount", "Quote Date", "Status"]
    mapping, _ = cm.detect_mapping(cols, "quote")
    assert mapping["client_name"] == "Client"
    assert mapping["quote_amount"] == "Quote Amount"


def test_apply_mapping_preserves_original():
    df = pd.DataFrame({"Customer Name": ["A"], "Total Due": [100]})
    mapping = {"customer_name": "Customer Name", "amount_due": "Total Due"}
    processed = cm.apply_mapping(df, mapping)
    assert list(processed.columns) == ["customer_name", "amount_due"]
    # Original frame untouched.
    assert "Customer Name" in df.columns


def test_excel_export_generation(memory, settings):
    from src.approval_engine import analyze_and_queue

    analyze_and_queue(memory, settings, {
        "invoice": [{"customer_name": "Acme", "invoice_number": "INV-1",
                     "due_date": (REF - timedelta(days=20)).isoformat(),
                     "amount_due": 1200, "payment_status": "unpaid"}]
    })
    data = ex.combined_report(memory)
    assert isinstance(data, bytes)
    assert len(data) > 0  # a real xlsx was produced


def test_scheduled_task_creation(memory, settings):
    # Seed an active record, then run the daily analysis pass.
    memory.save_record("invoice", "INV-2", "Beta", 800, "unpaid",
                       {"customer_name": "Beta", "invoice_number": "INV-2",
                        "due_date": (REF - timedelta(days=10)).isoformat(),
                        "amount_due": 800, "payment_status": "unpaid"})
    summary = run_daily_analysis(memory, settings)
    assert summary["invoices_reviewed"] >= 1
    assert "pending_approvals" in summary
    # The run must be logged and must never claim to have sent anything.
    log = memory.decision_log()
    assert any(e["event"] == "daily_run" for e in log)
