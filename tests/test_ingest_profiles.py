"""Tests for multi-client ingestion: robust reading, profiles, aliases, statuses."""

import io

import pandas as pd

from src import column_mapper as cm
from src import ingest
from src.approval_engine import analyze_and_queue


# --- Robust reading --------------------------------------------------------
def test_csv_semicolon_with_junk_header_rows():
    text = (
        "Acme Ltd — Quarterly Export\n"
        "Generated 2026-06-01\n"
        "Client;Inv No;Total Due;Due Date;Status\n"
        "Acme;INV-1;1.200,50;2026-01-01;O/S\n"
        "Beta;INV-2;900;2026-02-01;Paid\n"
    )
    df, meta = ingest.read_table(text.encode("utf-8"), "export.csv")
    assert meta["delimiter"] == ";"
    assert meta["header_row"] == 2  # skipped the two title rows
    assert "Client" in df.columns and "Total Due" in df.columns
    assert len(df) == 2


def test_excel_multi_sheet_pick():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"a": [1]}).to_excel(w, sheet_name="Summary", index=False)
        pd.DataFrame({"Client": ["X"], "Amount": [10]}).to_excel(w, sheet_name="Invoices", index=False)
    data = buf.getvalue()
    assert "Invoices" in ingest.excel_sheets(data)
    df, meta = ingest.read_table(data, "book.xlsx", sheet="Invoices")
    assert meta["sheet"] == "Invoices"
    assert "Client" in df.columns


# --- Learned aliases improve detection -------------------------------------
def test_detect_mapping_uses_learned_alias():
    cols = ["Customer", "Wonga", "Due Date"]
    # Without learning, "Wonga" is not recognised as the amount.
    mapping, _ = cm.detect_mapping(cols, "invoice")
    assert mapping.get("amount_due") != "Wonga"
    # After learning the alias, it is picked up.
    learned = {"amount_due": ["wonga"]}
    mapping2, _ = cm.detect_mapping(cols, "invoice", learned=learned)
    assert mapping2["amount_due"] == "Wonga"


# --- Header fingerprint + profile matching ---------------------------------
def test_signature_and_profile_match():
    cols_a = ["Client", "Inv No", "Total Due", "Due Date", "Status"]
    sig = cm.header_signature(cols_a)
    profile = {"header_signature": sig, "mapping": {"customer_name": "Client"}}
    # A near-identical file (one extra column) still matches.
    cols_b = ["Client", "Inv No", "Total Due", "Due Date", "Status", "Notes"]
    match = cm.match_profile([profile], cols_b)
    assert match is not None and match["match_score"] >= 0.6
    # A totally different file does not match.
    assert cm.match_profile([profile], ["Name", "Email", "Phone"]) is None


# --- Status vocabulary normalisation ---------------------------------------
def test_status_map_translates_client_words():
    suggested = cm.suggest_status_map(["O/S", "Paid", "In Dispute"], "invoice")
    assert suggested["o/s"] == "unpaid"
    assert suggested["paid"] == "paid"
    assert suggested["in dispute"] == "disputed"

    series = pd.Series(["O/S", "Paid", "weird-status"])
    out = cm.apply_status_map(series, {"O/S": "unpaid", "Paid": "paid"})
    assert list(out) == ["unpaid", "paid", "weird-status"]  # unmapped passes through


# --- Memory: profiles + alias learning -------------------------------------
def test_memory_profiles_and_alias_learning(memory):
    sig = cm.header_signature(["Client", "Inv No", "Total Due"])
    pid = memory.save_mapping_profile(
        "Acme Ltd", "invoice", {"customer_name": "Client", "amount_due": "Total Due"},
        signature=sig, status_map={"o/s": "unpaid"}, client="Acme",
    )
    assert pid
    profiles = memory.list_mapping_profiles("invoice")
    assert profiles and profiles[0]["mapping"]["customer_name"] == "Client"

    # Saving same name updates rather than duplicates.
    memory.save_mapping_profile("Acme Ltd", "invoice", {"customer_name": "Cust"}, signature=sig)
    assert len(memory.list_mapping_profiles("invoice")) == 1

    memory.learn_aliases("invoice", {"amount_due": "Total Due", "customer_name": "Client"})
    learned = memory.learned_aliases("invoice")
    assert "total due" in learned["amount_due"]

    memory.delete_mapping_profile(pid)
    assert memory.list_mapping_profiles("invoice") == []


# --- Full pipeline on a non-standard client file ---------------------------
def test_end_to_end_weird_client_file(memory, settings):
    text = (
        "GLOBEX CORP — AR EXPORT\n"
        "Customer Account;Doc Ref;Balance Outstanding;Payment By;State\n"
        "Globex;D-99;2.500,00;2026-01-01;O/S\n"
        "Initech;D-98;1000;2026-01-01;Closed\n"
    )
    df, meta = ingest.read_table(text.encode("utf-8"), "globex.csv")
    assert meta["delimiter"] == ";" and meta["header_row"] == 1

    mapping = {
        "customer_name": "Customer Account", "invoice_number": "Doc Ref",
        "amount_due": "Balance Outstanding", "due_date": "Payment By",
        "payment_status": "State",
    }
    status_map = cm.suggest_status_map(["O/S", "Closed"], "invoice")
    processed = cm.apply_mapping(df, mapping)
    processed["payment_status"] = cm.apply_status_map(processed["payment_status"], status_map)
    records = [{k: (None if pd.isna(v) else v) for k, v in r.items()}
               for r in processed.to_dict("records")]

    plan = analyze_and_queue(memory, settings, {"invoice": records})
    names = [s.name for s in plan]
    assert "Globex" in names
    globex = next(s for s in plan if s.name == "Globex")
    assert globex.amount == 2500.0          # European "2.500,00" parsed correctly
    assert globex.suggested_message          # an overdue/unpaid invoice got a reminder
    # Initech is "Closed" → translated to paid → no chasing message.
    initech = next((s for s in plan if s.name == "Initech"), None)
    assert initech is None or not initech.suggested_message
