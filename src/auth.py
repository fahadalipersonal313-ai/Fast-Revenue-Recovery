"""User accounts and per-tenant data isolation.

Design: each signed-up user is a "tenant." Every tenant gets their own SQLite
file under ``data/tenants/<slug>/recovery_desk.db`` — completely separate from
every other tenant's invoices, quotes, leads, and approvals. This re-uses the
existing ``AgentMemory``/``database`` layer unchanged (it already takes a
``path``); the only new code is account management and picking the right path.

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib ``hashlib``, no extra
dependency) with a unique salt per user. Plaintext passwords are never stored
or logged.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from .config import DATA_DIR

USERS_DB_PATH = DATA_DIR / "users.db"
TENANTS_DIR = DATA_DIR / "tenants"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    tenant_slug   TEXT NOT NULL UNIQUE,
    company_name  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);
"""

_PBKDF2_ITERATIONS = 200_000
_RESET_CODE_TTL_MINUTES = 30

# Columns added after the original schema shipped — applied idempotently so
# existing users.db files upgrade in place without losing data.
_MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN reset_code_hash TEXT",
    "ALTER TABLE users ADD COLUMN reset_expires_at TEXT",
)


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    for stmt in _MIGRATIONS:
        col = stmt.split("ADD COLUMN", 1)[1].split()[0]
        if col not in existing:
            conn.execute(stmt)


@dataclass
class User:
    id: int
    email: str
    tenant_slug: str
    company_name: str


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    USERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(USERS_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    ).hex()


def _slugify(email: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-") or "tenant"
    return base


def _unique_slug(base: str) -> str:
    with _connect() as conn:
        candidate = base
        suffix = 1
        while conn.execute(
            "SELECT 1 FROM users WHERE tenant_slug=?", (candidate,)
        ).fetchone():
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate


class AuthError(ValueError):
    """Raised for user-facing signup/login problems (bad email, wrong password, etc.)."""


def signup(email: str, password: str, company_name: str = "") -> User:
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise AuthError("Please enter a valid email address.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")

    salt = os.urandom(16).hex()
    pw_hash = _hash_password(password, salt)
    slug = _unique_slug(_slugify(email))

    with _connect() as conn:
        existing = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            raise AuthError("An account with this email already exists.")
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, salt, tenant_slug, company_name) "
            "VALUES (?,?,?,?,?)",
            (email, pw_hash, salt, slug, company_name.strip()),
        )
        user_id = int(cur.lastrowid)

    tenant_db_path(slug).parent.mkdir(parents=True, exist_ok=True)
    return User(id=user_id, email=email, tenant_slug=slug, company_name=company_name.strip())


def login(email: str, password: str) -> User:
    email = email.strip().lower()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, salt, tenant_slug, company_name "
            "FROM users WHERE email=?",
            (email,),
        ).fetchone()
    if not row:
        raise AuthError("No account with this email. Sign up first.")
    if _hash_password(password, row["salt"]) != row["password_hash"]:
        raise AuthError("Incorrect password.")
    return User(
        id=row["id"], email=row["email"], tenant_slug=row["tenant_slug"],
        company_name=row["company_name"] or "",
    )


def tenant_db_path(tenant_slug: str) -> Path:
    """The isolated SQLite file for one tenant's data — never shared across tenants."""
    return TENANTS_DIR / tenant_slug / "recovery_desk.db"


def find_user_by_id(user_id: int) -> Optional[User]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, tenant_slug, company_name FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return User(id=row["id"], email=row["email"], tenant_slug=row["tenant_slug"],
                company_name=row["company_name"] or "")


# ---------------------------------------------------------------------------
# Profile management (requires the user to be logged in)
# ---------------------------------------------------------------------------
def _verify_password(conn: sqlite3.Connection, user_id: int, password: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, email, password_hash, salt, tenant_slug, company_name "
        "FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not row:
        raise AuthError("Account not found.")
    if _hash_password(password, row["salt"]) != row["password_hash"]:
        raise AuthError("Current password is incorrect.")
    return row


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    """Set a new password after verifying the current one."""
    if len(new_password) < 8:
        raise AuthError("New password must be at least 8 characters.")
    with _connect() as conn:
        _verify_password(conn, user_id, current_password)
        salt = os.urandom(16).hex()
        conn.execute(
            "UPDATE users SET password_hash=?, salt=?, reset_code_hash=NULL, "
            "reset_expires_at=NULL WHERE id=?",
            (_hash_password(new_password, salt), salt, user_id),
        )


def change_email(user_id: int, current_password: str, new_email: str) -> User:
    """Change the account email after verifying the current password. The
    tenant slug (and therefore all the tenant's data) is unaffected."""
    new_email = new_email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        raise AuthError("Please enter a valid email address.")
    with _connect() as conn:
        row = _verify_password(conn, user_id, current_password)
        if new_email != row["email"]:
            clash = conn.execute(
                "SELECT 1 FROM users WHERE email=? AND id<>?", (new_email, user_id)
            ).fetchone()
            if clash:
                raise AuthError("Another account already uses this email.")
            conn.execute("UPDATE users SET email=? WHERE id=?", (new_email, user_id))
        return User(id=row["id"], email=new_email, tenant_slug=row["tenant_slug"],
                    company_name=row["company_name"] or "")


# ---------------------------------------------------------------------------
# Password reset (used pre-login; the code is delivered by app-level SMTP)
# ---------------------------------------------------------------------------
def request_password_reset(email: str) -> Optional[str]:
    """Generate and store a one-time reset code for ``email``.

    Returns the plain 6-digit code when the account exists (so the caller can
    email it), or ``None`` when it doesn't. Callers should show the *same*
    message either way to avoid leaking which emails are registered.
    """
    email = email.strip().lower()
    with _connect() as conn:
        row = conn.execute("SELECT id, salt FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            return None
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires = (datetime.now() + timedelta(minutes=_RESET_CODE_TTL_MINUTES))
        conn.execute(
            "UPDATE users SET reset_code_hash=?, reset_expires_at=? WHERE id=?",
            (_hash_password(code, row["salt"]), expires.isoformat(timespec="seconds"),
             row["id"]),
        )
        return code


def reset_password(email: str, code: str, new_password: str) -> None:
    """Verify a reset code and set a new password. Raises ``AuthError`` on any
    invalid/expired code or weak password."""
    email = email.strip().lower()
    code = (code or "").strip()
    if len(new_password) < 8:
        raise AuthError("New password must be at least 8 characters.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, salt, reset_code_hash, reset_expires_at FROM users WHERE email=?",
            (email,),
        ).fetchone()
        if not row or not row["reset_code_hash"] or not row["reset_expires_at"]:
            raise AuthError("No reset was requested for this email. Request a code first.")
        try:
            expired = datetime.now() > datetime.fromisoformat(row["reset_expires_at"])
        except ValueError:
            expired = True
        if expired:
            raise AuthError("This reset code has expired. Request a new one.")
        if _hash_password(code, row["salt"]) != row["reset_code_hash"]:
            raise AuthError("Incorrect reset code.")
        salt = os.urandom(16).hex()
        conn.execute(
            "UPDATE users SET password_hash=?, salt=?, reset_code_hash=NULL, "
            "reset_expires_at=NULL WHERE id=?",
            (_hash_password(new_password, salt), salt, row["id"]),
        )
