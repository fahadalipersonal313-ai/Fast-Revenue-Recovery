"""SQLite persistence layer.

This module owns the schema and connection handling only. Higher-level
behaviour (duplicate detection, history queries) lives in ``memory.py`` so the
storage concerns stay separate from the agent concerns.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type   TEXT NOT NULL,
    filename      TEXT,
    row_count     INTEGER DEFAULT 0,
    original_json TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    name_key   TEXT NOT NULL UNIQUE,
    email      TEXT,
    phone      TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type   TEXT NOT NULL,          -- invoice | quote | lead
    reference     TEXT,                   -- invoice/quote number, lead id
    customer_name TEXT,
    amount        REAL DEFAULT 0,
    status        TEXT,
    payload_json  TEXT,                   -- normalised record snapshot
    outcome       TEXT,                   -- recovered | won | converted | lost | open
    created_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(record_type, reference, customer_name)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type   TEXT NOT NULL,
    reference     TEXT,
    customer_name TEXT,
    amount        REAL DEFAULT 0,
    priority      TEXT,
    priority_score REAL DEFAULT 0,
    action        TEXT,
    reason        TEXT,
    stage         TEXT,
    message_kind  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type   TEXT,
    reference     TEXT,
    customer_name TEXT,
    channel       TEXT,
    kind          TEXT,
    subject       TEXT,
    body          TEXT,
    ai_improved   INTEGER DEFAULT 0,
    edited        INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type     TEXT NOT NULL,
    reference       TEXT,
    customer_name   TEXT,
    amount          REAL DEFAULT 0,
    priority        TEXT,
    priority_score  REAL DEFAULT 0,
    reason          TEXT,
    recommended_action TEXT,
    suggested_message  TEXT,
    suggested_channel  TEXT,
    next_follow_up_date TEXT,
    status          TEXT DEFAULT 'pending',  -- pending|approved|rejected|postponed|completed
    requires_approval INTEGER DEFAULT 1,
    decided_at      TEXT,
    note            TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS follow_up_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type   TEXT,
    reference     TEXT,
    customer_name TEXT,
    action        TEXT,
    due_date      TEXT,
    status        TEXT DEFAULT 'open',   -- open|done|cancelled
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payment_promises (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reference     TEXT,
    customer_name TEXT,
    promised_date TEXT,
    missed        INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type   TEXT,
    reference     TEXT,
    customer_name TEXT,
    event         TEXT,
    detail        TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- Saved per-client column mappings so a client's file layout is recognised and
-- applied automatically on future uploads.
CREATE TABLE IF NOT EXISTS mapping_profiles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    record_type      TEXT NOT NULL,
    client           TEXT,
    header_signature TEXT,                 -- fingerprint of the file's headers
    mapping_json     TEXT,                 -- {canonical_field: source_header}
    status_map_json  TEXT,                 -- {raw_status_value: canonical_token}
    header_row       INTEGER DEFAULT 0,
    sheet_name       TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(name, record_type)
);

-- Saved per-customer invoice "format" for the Invoice Generator: the field
-- layout + default line items + issuer details, so a customer's invoice can be
-- regenerated from a dropdown. One profile per customer (keyed by customer_key).
CREATE TABLE IF NOT EXISTS invoice_profiles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    customer_key  TEXT NOT NULL UNIQUE,     -- normalised customer name
    schema_json   TEXT,                     -- snapshot of the invoice form fields
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

-- Ledger of every invoice the generator produces. `source` distinguishes
-- human-made ('manual') from bulk auto-generated ('auto') so the Phase-3 bulk
-- path can refuse to overwrite a manual invoice for the same number.
CREATE TABLE IF NOT EXISTS generated_invoices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name  TEXT NOT NULL,
    customer_key   TEXT NOT NULL,           -- normalised customer name
    invoice_number TEXT,
    amount         REAL DEFAULT 0,
    currency       TEXT,
    source         TEXT NOT NULL DEFAULT 'manual',  -- manual | auto
    pdf_filename   TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(customer_key, invoice_number)
);

-- Every manual mapping the user confirms teaches the detector a new alias, so
-- auto-detection improves over time across all clients.
CREATE TABLE IF NOT EXISTS learned_aliases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    field       TEXT NOT NULL,
    header      TEXT NOT NULL,             -- normalised source header
    hits        INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(record_type, field, header)
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    """Create all tables if they do not yet exist."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_connection(path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Context-managed connection that commits on success and always closes."""
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Small generic helpers
# ---------------------------------------------------------------------------
def execute(sql: str, params: tuple = (), path: Path = DB_PATH) -> int:
    """Run a write statement; return lastrowid."""
    with get_connection(path) as conn:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid or 0)


def query(sql: str, params: tuple = (), path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Run a read statement; return a list of plain dicts."""
    with get_connection(path) as conn:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def query_one(
    sql: str, params: tuple = (), path: Path = DB_PATH
) -> Optional[Dict[str, Any]]:
    rows = query(sql, params, path)
    return rows[0] if rows else None
