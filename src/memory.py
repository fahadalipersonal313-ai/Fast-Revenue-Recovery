"""Agent memory: persistence built on top of the raw database layer.

Two responsibilities matter most here:

* **Duplicate prevention** — before any agent creates a new reminder or queue
  item we check whether an equivalent one already exists recently. This is the
  guard that stops the system spamming the same customer.
* **History** — every recommendation, message, approval and outcome is kept so
  the dashboard, customer history page and exports can reconstruct what
  happened and why.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import database as db
from . import crypto
from .config import DB_PATH, Settings
from .utils import clean_email, clean_phone, normalize_status


class AgentMemory:
    """A thin, well-named facade over the SQLite tables."""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        db.init_db(path)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    # These Settings fields hold secrets that must NEVER be written to the
    # plain `settings` table — they have their own encrypted storage
    # (save_email_credentials) or come from the environment only.
    _SECRET_SETTINGS_FIELDS = {"email_address_override", "email_app_password_override"}

    def load_settings(self) -> Settings:
        rows = db.query("SELECT key, value FROM settings", path=self.path)
        stored: Dict[str, Any] = {}
        for row in rows:
            if row["key"] in self._SECRET_SETTINGS_FIELDS:
                continue
            try:
                stored[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                stored[row["key"]] = row["value"]
        settings = Settings.from_dict(stored)
        address, app_password = self.load_email_credentials()
        settings.email_address_override = address
        settings.email_app_password_override = app_password
        return settings

    def save_settings(self, settings: Settings) -> None:
        # Persist everything except secrets (API key is env-only; email
        # credentials have their own encrypted storage, see above).
        data = {
            k: v for k, v in settings.to_dict().items()
            if k not in self._SECRET_SETTINGS_FIELDS
        }
        for key, value in data.items():
            db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
                path=self.path,
            )

    # ------------------------------------------------------------------
    # AI refine usage — per-tenant monthly counter for the Free-tier cap on
    # interactive AI refines (see gating.py). Stored as a month->count JSON map
    # in the settings KV table so it needs no schema change.
    # ------------------------------------------------------------------
    @staticmethod
    def _current_month_key() -> str:
        from datetime import datetime
        return datetime.utcnow().strftime("%Y-%m")

    def _ai_usage_map(self) -> Dict[str, int]:
        rows = db.query("SELECT value FROM settings WHERE key = 'ai_refine_usage'",
                        path=self.path)
        if not rows:
            return {}
        try:
            data = json.loads(rows[0]["value"])
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def ai_refine_usage_this_month(self) -> int:
        """How many interactive AI refines were used in the current month."""
        return int(self._ai_usage_map().get(self._current_month_key(), 0))

    def increment_ai_refine_usage(self) -> int:
        """Count one interactive AI refine for the current month; returns the
        new running total for the month."""
        usage = self._ai_usage_map()
        month = self._current_month_key()
        usage[month] = int(usage.get(month, 0)) + 1
        db.execute(
            "INSERT INTO settings(key, value) VALUES ('ai_refine_usage', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(usage),),
            path=self.path,
        )
        return usage[month]

    # ------------------------------------------------------------------
    # Per-tenant email credentials (encrypted at rest, never plain text)
    # ------------------------------------------------------------------
    def save_email_credentials(self, address: str, app_password: str) -> None:
        """Store this tenant's own email credentials, encrypted with the
        operator-controlled APP_SECRET_KEY (see crypto.py) — never in .env,
        never in plain text, never shared with other tenants."""
        db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("email_address_enc", json.dumps(crypto.encrypt(address.strip()))),
            path=self.path,
        )
        db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("email_app_password_enc", json.dumps(crypto.encrypt(app_password.strip()))),
            path=self.path,
        )

    def load_email_credentials(self) -> tuple[str, str]:
        """Return (address, app_password), decrypted. Empty strings if unset
        or if decryption fails (e.g. APP_SECRET_KEY changed)."""
        rows = db.query(
            "SELECT key, value FROM settings WHERE key IN ('email_address_enc','email_app_password_enc')",
            path=self.path,
        )
        stored = {r["key"]: json.loads(r["value"]) for r in rows}
        address = crypto.decrypt(stored.get("email_address_enc", "")) or ""
        app_password = crypto.decrypt(stored.get("email_app_password_enc", "")) or ""
        return address, app_password

    def clear_email_credentials(self) -> None:
        db.execute("DELETE FROM settings WHERE key IN ('email_address_enc','email_app_password_enc')",
                   path=self.path)

    # ------------------------------------------------------------------
    # First-run / onboarding state — used to auto-route brand-new signups
    # to the welcome page until they've explicitly dismissed it.
    # ------------------------------------------------------------------
    def onboarding_completed(self) -> bool:
        rows = db.query(
            "SELECT value FROM settings WHERE key='onboarding_completed_at'",
            path=self.path,
        )
        return bool(rows and rows[0]["value"])

    def mark_onboarding_completed(self) -> None:
        from datetime import datetime
        db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("onboarding_completed_at", json.dumps(datetime.utcnow().isoformat())),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # Customers and records
    # ------------------------------------------------------------------
    def upsert_customer(self, name: str, email: str = "", phone: str = "") -> None:
        if not name:
            return
        key = normalize_status(name)
        db.execute(
            "INSERT INTO customers(name, name_key, email, phone) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name_key) DO UPDATE SET "
            "  email = COALESCE(NULLIF(excluded.email, ''), customers.email), "
            "  phone = COALESCE(NULLIF(excluded.phone, ''), customers.phone)",
            (name, key, clean_email(email), clean_phone(phone)),
            path=self.path,
        )

    def get_customer_email(self, name: str) -> str:
        row = db.query_one(
            "SELECT email FROM customers WHERE name_key=?",
            (normalize_status(name),),
            path=self.path,
        )
        return (row or {}).get("email") or ""

    def save_record(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        amount: float,
        status: str,
        payload: Dict[str, Any],
        outcome: str = "open",
    ) -> None:
        ref = str(reference or "")
        # Defensive dedupe for files without proper reference numbers: if no
        # reference, match an existing record by (customer + amount + due_date)
        # and update it instead of inserting a near-duplicate. Prevents the
        # "uploaded twice = balance doubled" symptom on messy spreadsheets.
        if not ref.strip():
            due = str(payload.get("due_date") or payload.get("Due Date") or "")
            existing = db.query(
                "SELECT id, payload_json FROM records WHERE record_type=? "
                "AND customer_name=? AND amount=? AND reference='' LIMIT 5",
                (record_type, customer_name, float(amount or 0)),
                path=self.path,
            )
            for row in existing:
                try:
                    p = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    p = {}
                existing_due = str(p.get("due_date") or p.get("Due Date") or "")
                if existing_due == due:
                    db.execute(
                        "UPDATE records SET amount=?, status=?, payload_json=?, "
                        "outcome=? WHERE id=?",
                        (float(amount or 0), status,
                         json.dumps(payload, default=str), outcome, row["id"]),
                        path=self.path,
                    )
                    return
        db.execute(
            "INSERT INTO records"
            "(record_type, reference, customer_name, amount, status, payload_json, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(record_type, reference, customer_name) DO UPDATE SET "
            "  amount = excluded.amount, status = excluded.status, "
            "  payload_json = excluded.payload_json, outcome = excluded.outcome",
            (
                record_type,
                ref,
                customer_name,
                float(amount or 0),
                status,
                json.dumps(payload, default=str),
                outcome,
            ),
            path=self.path,
        )

    def update_record_outcome(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        status: str,
        outcome: str,
    ) -> None:
        """Mark a record paid/won/converted/lost and close its open queue items.

        This is the human-confirmed status change the safety rules require — the
        agents never flip a payment status by themselves.
        """
        db.execute(
            "UPDATE records SET status=?, outcome=? "
            "WHERE record_type=? AND reference=? AND customer_name=?",
            (status, outcome, record_type, str(reference or ""), customer_name),
            path=self.path,
        )
        db.execute(
            "UPDATE approvals SET status='completed', note=? "
            "WHERE record_type=? AND reference=? AND customer_name=? "
            "AND status IN ('pending','postponed')",
            (f"Closed: {outcome}", record_type, str(reference or ""), customer_name),
            path=self.path,
        )
        db.execute(
            "UPDATE follow_up_tasks SET status='done' "
            "WHERE record_type=? AND reference=? AND customer_name=? AND status='open'",
            (record_type, str(reference or ""), customer_name),
            path=self.path,
        )
        self.log_decision(record_type, reference, customer_name,
                          "outcome_updated", f"Marked {status} ({outcome}) by user.")

    def open_records(self, record_type: str) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT reference, customer_name, amount, status, outcome FROM records "
            "WHERE record_type=? ORDER BY customer_name",
            (record_type,),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # Recommendations + duplicate prevention
    # ------------------------------------------------------------------
    def has_recent_recommendation(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        within_days: int = 1,
    ) -> bool:
        """True if we already recommended an action for this record recently.

        This is the core anti-spam guard. ``within_days`` of 1 means "already
        handled in today's run".
        """
        row = db.query_one(
            "SELECT COUNT(*) AS n FROM recommendations "
            "WHERE record_type = ? AND reference = ? AND customer_name = ? "
            "AND created_at >= datetime('now', ?)",
            (record_type, str(reference or ""), customer_name, f"-{within_days} days"),
            path=self.path,
        )
        return bool(row and row["n"] > 0)

    def clear_recommendations(self, record_type: Optional[str] = None) -> None:
        """Wipe stored recommendations so a re-analyze doesn't accumulate
        duplicates row-by-row. Per-type if given, otherwise all of them."""
        if record_type:
            db.execute(
                "DELETE FROM recommendations WHERE record_type=?",
                (record_type,), path=self.path,
            )
        else:
            db.execute("DELETE FROM recommendations", path=self.path)

    def record_recommendation(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        amount: float,
        priority: str,
        priority_score: float,
        action: str,
        reason: str,
        stage: str = "",
        message_kind: str = "",
    ) -> int:
        return db.execute(
            "INSERT INTO recommendations"
            "(record_type, reference, customer_name, amount, priority, priority_score,"
            " action, reason, stage, message_kind) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                record_type,
                str(reference or ""),
                customer_name,
                float(amount or 0),
                priority,
                float(priority_score or 0),
                action,
                reason,
                stage,
                message_kind,
            ),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def has_message(
        self, record_type: str, reference: str, customer_name: str, kind: str
    ) -> bool:
        row = db.query_one(
            "SELECT COUNT(*) AS n FROM messages "
            "WHERE record_type = ? AND reference = ? AND customer_name = ? AND kind = ?",
            (record_type, str(reference or ""), customer_name, kind),
            path=self.path,
        )
        return bool(row and row["n"] > 0)

    def record_message(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        channel: str,
        kind: str,
        body: str,
        subject: str = "",
        ai_improved: bool = False,
        edited: bool = False,
    ) -> int:
        return db.execute(
            "INSERT INTO messages"
            "(record_type, reference, customer_name, channel, kind, subject, body,"
            " ai_improved, edited) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record_type,
                str(reference or ""),
                customer_name,
                channel,
                kind,
                subject,
                body,
                int(ai_improved),
                int(edited),
            ),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # Follow-up tasks
    # ------------------------------------------------------------------
    def add_follow_up_task(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        action: str,
        due_date: Optional[date],
    ) -> int:
        # Avoid stacking duplicate open tasks for the same record + due date.
        existing = db.query_one(
            "SELECT id FROM follow_up_tasks WHERE record_type=? AND reference=? "
            "AND customer_name=? AND due_date=? AND status='open'",
            (
                record_type,
                str(reference or ""),
                customer_name,
                due_date.isoformat() if due_date else None,
            ),
            path=self.path,
        )
        if existing:
            return int(existing["id"])
        return db.execute(
            "INSERT INTO follow_up_tasks"
            "(record_type, reference, customer_name, action, due_date) VALUES (?,?,?,?,?)",
            (
                record_type,
                str(reference or ""),
                customer_name,
                action,
                due_date.isoformat() if due_date else None,
            ),
            path=self.path,
        )

    def tasks_due(self, on_or_before: date) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT * FROM follow_up_tasks WHERE status='open' AND due_date IS NOT NULL "
            "AND due_date <= ? ORDER BY due_date",
            (on_or_before.isoformat(),),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # Payment promises
    # ------------------------------------------------------------------
    def record_payment_promise(
        self, reference: str, customer_name: str, promised_date: Optional[date], missed: bool
    ) -> int:
        return db.execute(
            "INSERT INTO payment_promises(reference, customer_name, promised_date, missed) "
            "VALUES (?,?,?,?)",
            (
                str(reference or ""),
                customer_name,
                promised_date.isoformat() if promised_date else None,
                int(missed),
            ),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # Decision log
    # ------------------------------------------------------------------
    def log_decision(
        self,
        record_type: str,
        reference: str,
        customer_name: str,
        event: str,
        detail: str = "",
    ) -> int:
        return db.execute(
            "INSERT INTO decision_log(record_type, reference, customer_name, event, detail) "
            "VALUES (?,?,?,?,?)",
            (record_type, str(reference or ""), customer_name, event, detail),
            path=self.path,
        )

    def decision_log(self, limit: int = 500) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT * FROM decision_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
            path=self.path,
        )

    # ------------------------------------------------------------------
    # History queries
    # ------------------------------------------------------------------
    def customer_history(self, customer_name: str) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "records": db.query(
                "SELECT * FROM records WHERE customer_name = ? ORDER BY created_at DESC",
                (customer_name,),
                path=self.path,
            ),
            "recommendations": db.query(
                "SELECT * FROM recommendations WHERE customer_name = ? "
                "ORDER BY created_at DESC",
                (customer_name,),
                path=self.path,
            ),
            "messages": db.query(
                "SELECT * FROM messages WHERE customer_name = ? ORDER BY created_at DESC",
                (customer_name,),
                path=self.path,
            ),
            "approvals": db.query(
                "SELECT * FROM approvals WHERE customer_name = ? ORDER BY created_at DESC",
                (customer_name,),
                path=self.path,
            ),
        }

    def all_customers(self) -> List[str]:
        rows = db.query("SELECT DISTINCT customer_name FROM records "
                        "WHERE customer_name <> '' ORDER BY customer_name", path=self.path)
        return [r["customer_name"] for r in rows]

    # ------------------------------------------------------------------
    # Mapping profiles (per-client column layouts)
    # ------------------------------------------------------------------
    def save_mapping_profile(
        self,
        name: str,
        record_type: str,
        mapping: Dict[str, str],
        signature: str = "",
        status_map: Optional[Dict[str, str]] = None,
        client: str = "",
        header_row: int = 0,
        sheet_name: str = "",
    ) -> int:
        return db.execute(
            "INSERT INTO mapping_profiles"
            "(name, record_type, client, header_signature, mapping_json, status_map_json,"
            " header_row, sheet_name, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?, datetime('now')) "
            "ON CONFLICT(name, record_type) DO UPDATE SET "
            "  client=excluded.client, header_signature=excluded.header_signature, "
            "  mapping_json=excluded.mapping_json, status_map_json=excluded.status_map_json, "
            "  header_row=excluded.header_row, sheet_name=excluded.sheet_name, "
            "  updated_at=datetime('now')",
            (
                name, record_type, client, signature,
                json.dumps(mapping or {}), json.dumps(status_map or {}),
                int(header_row or 0), sheet_name,
            ),
            path=self.path,
        )

    def list_mapping_profiles(
        self, record_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if record_type:
            rows = db.query(
                "SELECT * FROM mapping_profiles WHERE record_type=? ORDER BY name",
                (record_type,), path=self.path,
            )
        else:
            rows = db.query("SELECT * FROM mapping_profiles ORDER BY record_type, name",
                            path=self.path)
        for r in rows:
            r["mapping"] = json.loads(r.get("mapping_json") or "{}")
            r["status_map"] = json.loads(r.get("status_map_json") or "{}")
        return rows

    def get_mapping_profile(self, profile_id: int) -> Optional[Dict[str, Any]]:
        row = db.query_one("SELECT * FROM mapping_profiles WHERE id=?",
                           (profile_id,), path=self.path)
        if row:
            row["mapping"] = json.loads(row.get("mapping_json") or "{}")
            row["status_map"] = json.loads(row.get("status_map_json") or "{}")
        return row

    def delete_mapping_profile(self, profile_id: int) -> None:
        db.execute("DELETE FROM mapping_profiles WHERE id=?", (profile_id,), path=self.path)

    # ------------------------------------------------------------------
    # Invoice generator — per-customer profiles + generated-invoice ledger
    # ------------------------------------------------------------------
    def save_invoice_profile(self, customer_name: str, schema: Dict[str, Any]) -> int:
        """Create or update the saved invoice format for a customer.

        Keyed by the normalised customer name, so re-saving the same customer
        updates their one profile rather than piling up duplicates.
        """
        key = normalize_status(customer_name)
        if not key:
            return 0
        return db.execute(
            "INSERT INTO invoice_profiles(customer_name, customer_key, schema_json, updated_at) "
            "VALUES (?,?,?, datetime('now')) "
            "ON CONFLICT(customer_key) DO UPDATE SET "
            "  customer_name=excluded.customer_name, schema_json=excluded.schema_json, "
            "  updated_at=datetime('now')",
            (customer_name, key, json.dumps(schema or {}, default=str)),
            path=self.path,
        )

    def list_invoice_profiles(self) -> List[Dict[str, Any]]:
        rows = db.query("SELECT * FROM invoice_profiles ORDER BY customer_name",
                        path=self.path)
        for r in rows:
            r["schema"] = json.loads(r.get("schema_json") or "{}")
        return rows

    def get_invoice_profile_by_customer(self, customer_name: str) -> Optional[Dict[str, Any]]:
        row = db.query_one("SELECT * FROM invoice_profiles WHERE customer_key=?",
                           (normalize_status(customer_name),), path=self.path)
        if row:
            row["schema"] = json.loads(row.get("schema_json") or "{}")
        return row

    def delete_invoice_profile(self, profile_id: int) -> None:
        db.execute("DELETE FROM invoice_profiles WHERE id=?", (profile_id,), path=self.path)

    def record_generated_invoice(
        self,
        customer_name: str,
        invoice_number: str,
        amount: float,
        currency: str = "",
        source: str = "manual",
        pdf_filename: str = "",
    ) -> int:
        """Log a produced invoice. A manual invoice for a given
        (customer, number) updates the existing row; the Phase-3 bulk path uses
        ``manual_invoice_exists`` to avoid clobbering manual work."""
        key = normalize_status(customer_name)
        return db.execute(
            "INSERT INTO generated_invoices"
            "(customer_name, customer_key, invoice_number, amount, currency, source, "
            " pdf_filename, updated_at) VALUES (?,?,?,?,?,?,?, datetime('now')) "
            "ON CONFLICT(customer_key, invoice_number) DO UPDATE SET "
            "  customer_name=excluded.customer_name, amount=excluded.amount, "
            "  currency=excluded.currency, source=excluded.source, "
            "  pdf_filename=excluded.pdf_filename, updated_at=datetime('now')",
            (customer_name, key, str(invoice_number or ""), float(amount or 0),
             currency, source, pdf_filename),
            path=self.path,
        )

    def manual_invoice_exists(self, customer_name: str, invoice_number: str) -> bool:
        """True if a human-made invoice already exists for this
        (customer, number) — the guard the bulk auto-generator must honour."""
        row = db.query_one(
            "SELECT COUNT(*) AS n FROM generated_invoices "
            "WHERE customer_key=? AND invoice_number=? AND source='manual'",
            (normalize_status(customer_name), str(invoice_number or "")),
            path=self.path,
        )
        return bool(row and row["n"] > 0)

    # ------------------------------------------------------------------
    # Learned aliases (detector improves with every confirmed mapping)
    # ------------------------------------------------------------------
    def learn_aliases(self, record_type: str, mapping: Dict[str, str]) -> None:
        for field, header in (mapping or {}).items():
            norm = normalize_status(header)
            if not norm:
                continue
            db.execute(
                "INSERT INTO learned_aliases(record_type, field, header) VALUES (?,?,?) "
                "ON CONFLICT(record_type, field, header) DO UPDATE SET hits = hits + 1",
                (record_type, field, norm), path=self.path,
            )

    def learned_aliases(self, record_type: str) -> Dict[str, List[str]]:
        rows = db.query(
            "SELECT field, header FROM learned_aliases WHERE record_type=? "
            "ORDER BY hits DESC",
            (record_type,), path=self.path,
        )
        out: Dict[str, List[str]] = {}
        for r in rows:
            out.setdefault(r["field"], []).append(r["header"])
        return out
