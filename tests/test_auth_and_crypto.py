"""Tests for multi-tenant accounts (src/auth.py) and secret encryption (src/crypto.py)."""

from __future__ import annotations

import pytest

import src.auth as auth
import src.crypto as crypto


@pytest.fixture(autouse=True)
def isolated_users_db(tmp_path, monkeypatch):
    """Every test gets its own users/tenants DB — never touches real data/."""
    monkeypatch.setattr(auth, "USERS_DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "TENANTS_DIR", tmp_path / "tenants")


def test_signup_then_login():
    auth.signup("owner@example.com", "supersecret1", "Acme Co")
    user = auth.login("owner@example.com", "supersecret1")
    assert user.email == "owner@example.com"
    assert user.company_name == "Acme Co"
    assert user.tenant_slug


def test_login_wrong_password_rejected():
    auth.signup("owner@example.com", "supersecret1")
    with pytest.raises(auth.AuthError):
        auth.login("owner@example.com", "wrongpassword")


def test_login_unknown_email_rejected():
    with pytest.raises(auth.AuthError):
        auth.login("nobody@example.com", "whatever123")


def test_signup_duplicate_email_rejected():
    auth.signup("owner@example.com", "supersecret1")
    with pytest.raises(auth.AuthError):
        auth.signup("owner@example.com", "anotherpassword")


def test_signup_short_password_rejected():
    with pytest.raises(auth.AuthError):
        auth.signup("owner@example.com", "short")


def test_signup_invalid_email_rejected():
    with pytest.raises(auth.AuthError):
        auth.signup("not-an-email", "supersecret1")


def test_two_tenants_get_different_isolated_db_paths():
    u1 = auth.signup("a@example.com", "supersecret1")
    u2 = auth.signup("b@example.com", "supersecret1")
    assert auth.tenant_db_path(u1.tenant_slug) != auth.tenant_db_path(u2.tenant_slug)
    assert u1.tenant_slug != u2.tenant_slug


def test_password_never_stored_in_plain_text():
    auth.signup("owner@example.com", "supersecret1")
    with auth._connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email=?", ("owner@example.com",)
        ).fetchone()
    assert "supersecret1" not in row["password_hash"]


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------
def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "a-test-secret-key")
    crypto._fernet.cache_clear()
    ciphertext = crypto.encrypt("my-app-password")
    assert ciphertext != "my-app-password"
    assert crypto.decrypt(ciphertext) == "my-app-password"
    crypto._fernet.cache_clear()


def test_decrypt_garbage_returns_none(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "a-test-secret-key")
    crypto._fernet.cache_clear()
    assert crypto.decrypt("not-valid-ciphertext") is None
    crypto._fernet.cache_clear()


def test_empty_string_roundtrip(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "a-test-secret-key")
    crypto._fernet.cache_clear()
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") is None
    crypto._fernet.cache_clear()
