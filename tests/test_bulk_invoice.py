"""Phase 3 — bulk invoice generation (pure layer)."""

from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO

from src import bulk_invoice as bulk
from src import column_mapper as cm


ISSUER = {"company": "My Co", "email": "me@myco.example", "address": "1 Main St"}


def _plan(rows, *, manual=None, profiles=None):
    manual = manual or set()
    profiles = profiles or {}
    return bulk.plan_rows(
        rows,
        manual_exists=lambda c, n: (c, n) in manual,
        get_profile=lambda name: profiles.get(name),
        default_issuer=ISSUER,
        default_currency="$",
    )


def test_ready_row_builds_invoice_data():
    res = _plan([{"customer_name": "Acme", "invoice_number": "INV-1",
                  "amount_due": "1,250.50"}])
    assert len(res) == 1
    r = res[0]
    assert r.status == bulk.READY
    assert r.data.customer_name == "Acme"
    assert r.data.from_company == "My Co"          # issuer fallback
    assert r.data.line_items[0].unit_price == 1250.50  # comma stripped


def test_missing_customer_is_error():
    res = _plan([{"customer_name": "", "amount_due": "100"}])
    assert res[0].status == bulk.ERROR
    assert "customer" in res[0].reason.lower()


def test_missing_or_zero_amount_is_error():
    res = _plan([{"customer_name": "Acme", "amount_due": ""},
                 {"customer_name": "Beta", "amount_due": "0"},
                 {"customer_name": "Gamma", "amount_due": "abc"}])
    assert [r.status for r in res] == [bulk.ERROR, bulk.ERROR, bulk.ERROR]


def test_manual_invoice_is_skipped_not_overwritten():
    res = _plan(
        [{"customer_name": "Acme", "invoice_number": "INV-1", "amount_due": "100"}],
        manual={("Acme", "INV-1")},
    )
    assert res[0].status == bulk.SKIPPED_MANUAL


def test_blank_invoice_number_never_trips_manual_guard():
    # No number → can't match a manual record → should be READY.
    res = _plan(
        [{"customer_name": "Acme", "invoice_number": "", "amount_due": "100"}],
        manual={("Acme", "")},
    )
    assert res[0].status == bulk.READY


def test_profile_supplies_currency_tax_and_branding():
    schema = {"from_company": "Profiled Co", "currency": "£", "tax_rate": 20.0,
              "customer_address": "9 Client Rd", "notes": "Net 14"}
    res = _plan(
        [{"customer_name": "Acme", "invoice_number": "INV-9", "amount_due": "200"}],
        profiles={"Acme": schema},
    )
    r = res[0]
    assert r.data.from_company == "Profiled Co"
    assert r.data.currency_symbol == "£"
    assert r.data.tax_rate_percent == 20.0
    assert r.data.customer_address == "9 Client Rd"
    assert r.data.notes == "Net 14"
    # The amount still comes from the row, not the profile.
    assert r.data.line_items[0].unit_price == 200.0


def test_dates_parsed_from_common_formats():
    res = _plan([{"customer_name": "Acme", "invoice_number": "INV-1",
                  "amount_due": "100", "due_date": "31/12/2026",
                  "invoice_date": "2026-01-15"}])
    assert res[0].data.due_date == date(2026, 12, 31)
    assert res[0].data.issue_date == date(2026, 1, 15)


def test_summarize_counts():
    res = _plan(
        [{"customer_name": "Acme", "invoice_number": "INV-1", "amount_due": "100"},
         {"customer_name": "", "amount_due": "100"},
         {"customer_name": "Beta", "invoice_number": "INV-2", "amount_due": "50"}],
        manual={("Beta", "INV-2")},
    )
    counts = bulk.summarize(res)
    assert counts == {bulk.READY: 1, bulk.SKIPPED_MANUAL: 1, bulk.ERROR: 1, "total": 3}


def test_render_all_and_zip_roundtrip():
    res = _plan(
        [{"customer_name": "Acme", "invoice_number": "INV-1", "amount_due": "100"},
         {"customer_name": "Beta", "invoice_number": "INV-2", "amount_due": "200"}])
    ready = [r for r in res if r.status == bulk.READY]
    rendered = bulk.render_all(ready)
    assert len(rendered) == 2
    for _r, name, pdf in rendered:
        assert name.endswith(".pdf")
        assert pdf[:4] == b"%PDF"
    zbytes = bulk.zip_pdfs(rendered)
    with zipfile.ZipFile(BytesIO(zbytes)) as zf:
        assert len(zf.namelist()) == 2


def test_company_contact_mobile_address_compose_into_billto():
    res = _plan([{"company_name": "Acme Ltd", "contact_person": "Jane Roe",
                  "address": "9 Client Rd", "mobile_number": "0300-1234567",
                  "amount_due": "500", "invoice_number": "INV-7"}])
    r = res[0]
    assert r.status == bulk.READY
    # No explicit customer_name → company becomes the heading.
    assert r.data.customer_name == "Acme Ltd"
    block = r.data.customer_address
    assert "Attn: Jane Roe" in block
    assert "9 Client Rd" in block
    assert "Mobile: 0300-1234567" in block
    # Identity/label falls back to company name for dedup + ledger.
    assert r.customer_name == "Acme Ltd"


def test_customer_name_is_heading_company_goes_to_address():
    res = _plan([{"customer_name": "Bob", "company_name": "Acme Ltd",
                  "amount_due": "100"}])
    r = res[0]
    assert r.data.customer_name == "Bob"
    assert "Acme Ltd" in r.data.customer_address


def test_invoice_bulk_fieldset_detects_new_columns():
    mapping, _ = cm.detect_mapping(
        ["Company Name", "Contact Person", "Mobile", "Email", "Address", "Amount"],
        "invoice_bulk")
    assert mapping["company_name"] == "Company Name"
    assert mapping["contact_person"] == "Contact Person"
    assert mapping["mobile_number"] == "Mobile"
    assert mapping["email"] == "Email"
    assert mapping["address"] == "Address"
    assert mapping["amount_due"] == "Amount"


def test_learned_alias_improves_bulk_detection(memory):
    # An unusual header the built-in aliases don't know.
    memory.learn_aliases("invoice_bulk", {"customer_name": "Punter"})
    learned = memory.learned_aliases("invoice_bulk")
    mapping, _ = cm.detect_mapping(["Punter", "Amount"], "invoice_bulk", learned=learned)
    assert mapping["customer_name"] == "Punter"


def test_render_all_dedupes_identical_filenames():
    # Same customer + same (blank) number twice → suggest_filename collides.
    res = _plan(
        [{"customer_name": "Acme", "invoice_number": "", "amount_due": "100"},
         {"customer_name": "Acme", "invoice_number": "", "amount_due": "200"}])
    rendered = bulk.render_all([r for r in res if r.status == bulk.READY])
    names = [name for _r, name, _pdf in rendered]
    assert len(names) == len(set(names))  # all unique
