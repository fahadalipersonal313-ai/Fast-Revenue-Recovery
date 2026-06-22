"""Tests for the quote generator, bulk quote planning, standardized templates,
the invoice renderer's new branding/custom-field inputs, and AI custom-field
analysis. PDF *content* isn't asserted (binary) — we check it renders to a valid
PDF, that pure logic (totals/records/planning) is correct, and that every new
path fails safe."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import pytest
from PIL import Image as PImage

import src.ai_helper as ai
from src import bulk_quote as bq
from src import column_mapper as cm
from src import invoice_generator as ig
from src import quote_generator as qg
from src import templates


def _png(w=120, h=60, color=(10, 20, 40)) -> bytes:
    buf = BytesIO()
    PImage.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# --- quote generator -------------------------------------------------------
def _quote(**over) -> qg.QuoteData:
    base = dict(from_company="Test Co", customer_name="Acme Ltd", quote_number="Q-1",
                quote_date=date(2026, 6, 1), valid_until=date(2026, 7, 1),
                line_items=[qg.LineItem("Design", 2, 250.0)], tax_rate_percent=10.0)
    base.update(over)
    return qg.QuoteData(**base)


def test_quote_totals_and_record():
    data = _quote()
    totals = qg.compute_totals(data)
    assert totals["subtotal"] == 500.0 and totals["tax"] == 50.0 and totals["total"] == 550.0
    rec = qg.to_record(data)
    assert rec["client_name"] == "Acme Ltd"
    assert rec["quote_amount"] == 550.0
    assert rec["quote_date"] == "2026-06-01"


def test_quote_pdf_renders():
    pdf = qg.render_quote_pdf(_quote())
    assert pdf[:5] == b"%PDF-" and len(pdf) > 800


def test_quote_validation_rejects_empty_items():
    with pytest.raises(qg.QuoteError):
        qg.render_quote_pdf(_quote(line_items=[]))


def test_quote_renders_with_branding_and_custom_fields():
    data = _quote(custom_fields=[qg.CustomField("Project", "Rebrand")],
                  letterhead_png=_png(), signature_png=_png(), signature_label="For Co")
    assert qg.render_quote_pdf(data)[:5] == b"%PDF-"


def test_suggest_filename_is_safe():
    assert qg.suggest_filename(_quote(customer_name="A/B Co", quote_number="Q 9")) \
        == "quote_A_B_Co_Q_9.pdf"


# --- invoice renderer new inputs ------------------------------------------
def test_invoice_ignores_unreadable_images():
    data = ig.InvoiceData(from_company="Co", customer_name="Cust",
                          line_items=[ig.LineItem("x", 1, 10.0)],
                          letterhead_png=b"not-an-image", signature_png=b"junk")
    assert ig.render_invoice_pdf(data)[:5] == b"%PDF-"


def test_invoice_renders_custom_fields():
    data = ig.InvoiceData(from_company="Co", customer_name="Cust",
                          line_items=[ig.LineItem("x", 1, 10.0)],
                          custom_fields=[ig.CustomField("PO", "PO-1"),
                                         ig.CustomField("", "ignored")])
    assert ig.render_invoice_pdf(data)[:5] == b"%PDF-"


# --- bulk quote ------------------------------------------------------------
def test_bulk_quote_plan_render_zip():
    rows = [
        {"customer_name": "Bright", "quote_number": "Q-1", "amount_due": 500,
         "quote_date": "2026-06-01", "valid_until": "2026-07-01", "description": "Work"},
        {"customer_name": "", "company_name": "", "amount_due": 10},          # error: no name
        {"customer_name": "NoAmt", "amount_due": 0},                          # error: amount
    ]
    res = bq.plan_rows(rows, manual_exists=lambda c, n: False,
                       get_profile=lambda n: None,
                       default_issuer={"company": "Me"})
    counts = bq.summarize(res)
    assert counts[bq.READY] == 1 and counts[bq.ERROR] == 2 and counts["total"] == 3
    rendered = bq.render_all(res)
    assert len(rendered) == 1
    zipped = bq.zip_pdfs(rendered)
    assert zipped[:2] == b"PK"  # zip magic


def test_bulk_quote_skips_existing_manual():
    rows = [{"customer_name": "Dup", "quote_number": "Q-9", "amount_due": 100}]
    res = bq.plan_rows(rows, manual_exists=lambda c, n: True,
                       get_profile=lambda n: None, default_issuer={"company": "Me"})
    assert res[0].status == bq.SKIPPED_MANUAL


# --- templates -------------------------------------------------------------
@pytest.mark.parametrize("kind,rtype", [("invoice", "invoice_bulk"), ("quote", "quote_bulk")])
def test_template_autodetects_every_column(kind, rtype):
    raw = templates.build_template_xlsx(kind)
    df = pd.read_excel(BytesIO(raw))
    mapping, unmapped = cm.detect_mapping(list(df.columns), rtype)
    assert unmapped == []  # an unedited template maps with zero manual work
    assert templates.template_filename(kind) == f"{kind}_template.xlsx"


def test_template_headers_match_builder():
    assert templates.template_headers("invoice")[0] == "Customer Name"
    assert "Valid Until" in templates.template_headers("quote")


# --- AI custom-field analysis ---------------------------------------------
def test_analyze_custom_fields_none_when_ai_off(settings):
    assert ai.analyze_custom_fields(settings, [("po number", "PO-1")]) is None


def test_analyze_custom_fields_cleans_labels(monkeypatch, settings):
    monkeypatch.setattr(ai, "ai_available", lambda s: True)
    monkeypatch.setattr(ai, "_complete",
                        lambda system, prompt, settings, max_tokens:
                        '[{"label":"PO Number","value":"PO-1"},'
                        '{"label":"VAT ID","value":"GB123"}]')
    out = ai.analyze_custom_fields(settings, [("po number", "PO-1"), ("vat id", "GB123")])
    assert out == [("PO Number", "PO-1"), ("VAT ID", "GB123")]


def test_analyze_custom_fields_rejects_changed_numbers(monkeypatch, settings):
    # If the model alters a value's digits, distrust the whole response.
    monkeypatch.setattr(ai, "ai_available", lambda s: True)
    monkeypatch.setattr(ai, "_complete",
                        lambda *a, **k: '[{"label":"PO Number","value":"PO-999"}]')
    assert ai.analyze_custom_fields(settings, [("po number", "PO-1")]) is None


def test_analyze_custom_fields_rejects_length_mismatch(monkeypatch, settings):
    monkeypatch.setattr(ai, "ai_available", lambda s: True)
    monkeypatch.setattr(ai, "_complete", lambda *a, **k: '[]')
    assert ai.analyze_custom_fields(settings, [("a", "1")]) is None
