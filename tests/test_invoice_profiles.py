"""Phase 2 — invoice profiles + generated-invoice ledger (memory layer)."""

from __future__ import annotations

from src import database as db


def _schema(**overrides) -> dict:
    base = {
        "from_company": "Test Co",
        "customer_name": "Acme Ltd",
        "customer_email": "ap@acme.example",
        "currency": "$",
        "tax_rate": 8.5,
        "line_items": [
            {"Description": "Consulting", "Quantity": 10, "Unit price": 150.0},
        ],
        "notes": "Net 30",
    }
    base.update(overrides)
    return base


def test_save_and_get_invoice_profile(memory):
    memory.save_invoice_profile("Acme Ltd", _schema())
    got = memory.get_invoice_profile_by_customer("Acme Ltd")
    assert got is not None
    assert got["customer_name"] == "Acme Ltd"
    assert got["schema"]["tax_rate"] == 8.5
    assert got["schema"]["line_items"][0]["Description"] == "Consulting"


def test_profile_lookup_is_case_insensitive(memory):
    memory.save_invoice_profile("Acme Ltd", _schema())
    # normalize_status keys the lookup, so casing/spacing shouldn't matter.
    assert memory.get_invoice_profile_by_customer("acme   ltd") is not None


def test_resaving_profile_updates_not_duplicates(memory):
    memory.save_invoice_profile("Acme Ltd", _schema(tax_rate=8.5))
    memory.save_invoice_profile("Acme Ltd", _schema(tax_rate=20.0))
    profiles = memory.list_invoice_profiles()
    assert len(profiles) == 1
    assert profiles[0]["schema"]["tax_rate"] == 20.0


def test_list_invoice_profiles_sorted(memory):
    memory.save_invoice_profile("Zeta", _schema(customer_name="Zeta"))
    memory.save_invoice_profile("Alpha", _schema(customer_name="Alpha"))
    names = [p["customer_name"] for p in memory.list_invoice_profiles()]
    assert names == ["Alpha", "Zeta"]


def test_delete_invoice_profile(memory):
    memory.save_invoice_profile("Acme Ltd", _schema())
    pid = memory.list_invoice_profiles()[0]["id"]
    memory.delete_invoice_profile(pid)
    assert memory.list_invoice_profiles() == []


def test_blank_customer_name_saves_nothing(memory):
    assert memory.save_invoice_profile("", _schema()) == 0
    assert memory.list_invoice_profiles() == []


def test_record_generated_invoice_and_manual_guard(memory):
    memory.record_generated_invoice("Acme Ltd", "INV-001", 2061.50, "$",
                                    source="manual", pdf_filename="x.pdf")
    assert memory.manual_invoice_exists("Acme Ltd", "INV-001") is True
    # Different number / different customer must not trip the guard.
    assert memory.manual_invoice_exists("Acme Ltd", "INV-002") is False
    assert memory.manual_invoice_exists("Beta", "INV-001") is False


def test_auto_invoice_does_not_count_as_manual(memory):
    memory.record_generated_invoice("Acme Ltd", "INV-009", 100.0, "$", source="auto")
    assert memory.manual_invoice_exists("Acme Ltd", "INV-009") is False


def test_regenerating_same_invoice_number_updates_row(memory):
    memory.record_generated_invoice("Acme Ltd", "INV-001", 100.0, "$", source="manual")
    memory.record_generated_invoice("Acme Ltd", "INV-001", 250.0, "$", source="manual")
    rows = db.query("SELECT * FROM generated_invoices", path=memory.path)
    assert len(rows) == 1
    assert rows[0]["amount"] == 250.0
