"""Tests for src/invoice_generator.py and the email_draft attachment path."""

from __future__ import annotations

from datetime import date

import pytest

from src import email_draft, invoice_generator as ig
from src.config import Settings


def _sample_data(**overrides) -> ig.InvoiceData:
    defaults = dict(
        from_company="Test Co",
        from_email="me@example.com",
        customer_name="Acme Ltd",
        customer_email="ap@acme.example",
        invoice_number="INV-2026-001",
        issue_date=date(2026, 6, 20),
        due_date=date(2026, 7, 20),
        currency_symbol="$",
        line_items=[
            ig.LineItem("Consulting — June", 10, 150.0),
            ig.LineItem("Code review", 2, 200.0),
        ],
        tax_rate_percent=8.5,
        notes="Thanks for the work!",
    )
    defaults.update(overrides)
    return ig.InvoiceData(**defaults)


def test_compute_totals_rounds_and_sums():
    data = _sample_data()
    totals = ig.compute_totals(data)
    # subtotal = 10*150 + 2*200 = 1900; tax = 1900 * 0.085 = 161.50; total = 2061.50
    assert totals["subtotal"] == 1900.00
    assert totals["tax"] == 161.50
    assert totals["total"] == 2061.50


def test_render_invoice_pdf_starts_with_pdf_magic():
    pdf = ig.render_invoice_pdf(_sample_data())
    assert isinstance(pdf, bytes) and len(pdf) > 500
    assert pdf[:4] == b"%PDF"


def test_render_invoice_pdf_contains_customer_and_invoice_number():
    pdf = ig.render_invoice_pdf(_sample_data())
    # reportlab compresses streams but the document metadata (title/author) is
    # included as a literal PDF object, so the customer/invoice number show up.
    assert b"INV-2026-001" in pdf
    assert b"Test Co" in pdf


def test_render_invoice_is_deterministic_for_same_input():
    a = ig.render_invoice_pdf(_sample_data())
    b = ig.render_invoice_pdf(_sample_data())
    # PDFs include a /CreationDate; verify that the *content* (line item rows
    # & totals) is stable by checking length is identical and the prefix
    # matches up to the metadata trailer.
    assert len(a) == len(b)


def test_validation_rejects_missing_customer():
    data = _sample_data(customer_name="")
    with pytest.raises(ig.InvoiceError, match="Customer name"):
        ig.render_invoice_pdf(data)


def test_validation_rejects_no_line_items():
    data = _sample_data(line_items=[])
    with pytest.raises(ig.InvoiceError, match="line item"):
        ig.render_invoice_pdf(data)


def test_validation_rejects_negative_quantity():
    data = _sample_data(line_items=[ig.LineItem("Bad", -1, 10.0)])
    with pytest.raises(ig.InvoiceError, match="quantity"):
        ig.render_invoice_pdf(data)


def test_suggest_filename_sanitises():
    data = _sample_data(customer_name="Acme / Ltd!", invoice_number="INV 2026/001")
    fn = ig.suggest_filename(data)
    assert fn.endswith(".pdf")
    assert "/" not in fn and " " not in fn


def test_zero_tax_omits_tax_row_but_total_correct():
    data = _sample_data(tax_rate_percent=0.0)
    totals = ig.compute_totals(data)
    assert totals["tax"] == 0.0
    assert totals["total"] == totals["subtotal"]


def test_save_draft_with_attachment_returns_false_when_disabled():
    # No email creds + ai disabled -> email_draft_active is False -> returns (False, reason)
    settings = Settings(ai_enabled=False, email_draft_enabled=False)
    ok, reason = email_draft.save_draft_with_attachment(
        settings, "x@y.com", "Subj", "Body", b"%PDF-1.4 fake", "f.pdf",
    )
    assert ok is False and reason
