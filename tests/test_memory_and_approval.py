"""Tests for SQLite memory, duplicate prevention, approval queue and scheduling."""

from datetime import date, timedelta

from src.approval_engine import (
    analyze_and_queue,
    approve,
    list_queue,
    reject,
)

REF = date(2026, 6, 14)


def _invoice_records():
    return {
        "invoice": [
            {"customer_name": "Acme", "invoice_number": "INV-1",
             "due_date": (REF - timedelta(days=20)).isoformat(),
             "amount_due": 1200, "payment_status": "unpaid"},
        ]
    }


def test_sqlite_memory_storage(memory, settings):
    memory.upsert_customer("Acme", "a@b.com", "+15551112222")
    memory.save_record("invoice", "INV-1", "Acme", 1200, "unpaid", {"x": 1})
    hist = memory.customer_history("Acme")
    assert len(hist["records"]) == 1
    assert "Acme" in memory.all_customers()


def test_recommendation_recorded_and_dedup(memory, settings):
    plan = analyze_and_queue(memory, settings, _invoice_records())
    assert plan
    # Duplicate guard: a recommendation already exists for today.
    assert memory.has_recent_recommendation("invoice", "INV-1", "Acme", within_days=1)


def test_duplicate_action_prevention_no_double_queue(memory, settings):
    analyze_and_queue(memory, settings, _invoice_records())
    first = len(list_queue(memory, "pending"))
    analyze_and_queue(memory, settings, _invoice_records())  # run again
    second = len(list_queue(memory, "pending"))
    assert first == second  # no duplicate queue entry


def test_approval_schedules_follow_up_task(memory, settings):
    analyze_and_queue(memory, settings, _invoice_records())
    item = list_queue(memory, "pending")[0]
    approve(memory, item["id"], edited_message="Edited message")
    refreshed = list_queue(memory, "approved")
    assert refreshed and refreshed[0]["status"] == "approved"
    # A follow-up task must have been created (scheduled next action).
    assert memory.tasks_due(REF + timedelta(days=60))


def test_reject_marks_rejected(memory, settings):
    analyze_and_queue(memory, settings, _invoice_records())
    item = list_queue(memory, "pending")[0]
    reject(memory, item["id"], "not now")
    assert list_queue(memory, "rejected")


def test_mark_outcome_closes_pending_approvals(memory, settings):
    analyze_and_queue(memory, settings, _invoice_records())
    assert list_queue(memory, "pending")
    memory.update_record_outcome("invoice", "INV-1", "Acme", "Paid", "recovered")
    # Pending approvals for this record are resolved, and the record is updated.
    assert len(list_queue(memory, "pending")) == 0
    rec = memory.open_records("invoice")[0]
    assert rec["status"] == "Paid" and rec["outcome"] == "recovered"


def test_email_credentials_round_trip_and_are_encrypted(memory, monkeypatch):
    import src.crypto as crypto

    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-for-memory")
    crypto._fernet.cache_clear()

    memory.save_email_credentials("owner@example.com", "an-app-password")
    address, app_password = memory.load_email_credentials()
    assert address == "owner@example.com"
    assert app_password == "an-app-password"

    # The raw DB row must never contain the plain-text password.
    from src import database as db
    rows = db.query("SELECT value FROM settings WHERE key='email_app_password_enc'",
                     path=memory.path)
    assert "an-app-password" not in rows[0]["value"]
    crypto._fernet.cache_clear()


def test_clear_email_credentials(memory, monkeypatch):
    import src.crypto as crypto

    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-for-memory")
    crypto._fernet.cache_clear()

    memory.save_email_credentials("owner@example.com", "an-app-password")
    memory.clear_email_credentials()
    address, app_password = memory.load_email_credentials()
    assert address == "" and app_password == ""
    crypto._fernet.cache_clear()


def test_load_settings_never_persists_email_secrets_in_plain_settings_table(memory, monkeypatch, settings):
    import src.crypto as crypto

    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-for-memory")
    crypto._fernet.cache_clear()

    memory.save_email_credentials("owner@example.com", "an-app-password")
    loaded = memory.load_settings()
    assert loaded.email_address_override == "owner@example.com"
    memory.save_settings(loaded)  # must not leak the override into the plain table

    from src import database as db
    rows = db.query(
        "SELECT key FROM settings WHERE key IN ('email_address_override','email_app_password_override')",
        path=memory.path,
    )
    assert rows == []
    crypto._fernet.cache_clear()
