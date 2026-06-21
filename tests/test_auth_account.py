"""Account management: profile updates + password reset + app-level mailer."""

from __future__ import annotations

import pytest

from src import auth, mailer


@pytest.fixture
def users_db(tmp_path, monkeypatch):
    """Point the auth module at an isolated users.db for each test."""
    monkeypatch.setattr(auth, "USERS_DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "TENANTS_DIR", tmp_path / "tenants")
    return tmp_path


def _make_user(email="owner@acme.com", pw="origpass1"):
    return auth.signup(email, pw, "Acme")


# --- change password -------------------------------------------------------
def test_change_password_requires_correct_current(users_db):
    u = _make_user()
    with pytest.raises(auth.AuthError):
        auth.change_password(u.id, "wrongpass", "newpass12")
    auth.change_password(u.id, "origpass1", "newpass12")
    # Old password no longer works; new one does.
    with pytest.raises(auth.AuthError):
        auth.login("owner@acme.com", "origpass1")
    assert auth.login("owner@acme.com", "newpass12").id == u.id


def test_change_password_min_length(users_db):
    u = _make_user()
    with pytest.raises(auth.AuthError):
        auth.change_password(u.id, "origpass1", "short")


# --- change email ----------------------------------------------------------
def test_change_email_success_keeps_tenant(users_db):
    u = _make_user()
    updated = auth.change_email(u.id, "origpass1", "new@acme.com")
    assert updated.email == "new@acme.com"
    assert updated.tenant_slug == u.tenant_slug          # data stays put
    assert auth.login("new@acme.com", "origpass1").id == u.id


def test_change_email_rejects_duplicate(users_db):
    u1 = _make_user("a@acme.com")
    _make_user("b@acme.com")
    with pytest.raises(auth.AuthError):
        auth.change_email(u1.id, "origpass1", "b@acme.com")


def test_change_email_wrong_password(users_db):
    u = _make_user()
    with pytest.raises(auth.AuthError):
        auth.change_email(u.id, "nope", "new@acme.com")


# --- password reset --------------------------------------------------------
def test_reset_flow_happy_path(users_db):
    _make_user("r@acme.com", "origpass1")
    code = auth.request_password_reset("r@acme.com")
    assert code and len(code) == 6 and code.isdigit()
    auth.reset_password("r@acme.com", code, "brandnew1")
    assert auth.login("r@acme.com", "brandnew1").email == "r@acme.com"


def test_reset_unknown_email_returns_none(users_db):
    _make_user("r@acme.com")
    assert auth.request_password_reset("ghost@acme.com") is None


def test_reset_wrong_code_rejected(users_db):
    _make_user("r@acme.com")
    auth.request_password_reset("r@acme.com")
    with pytest.raises(auth.AuthError):
        auth.reset_password("r@acme.com", "000000", "brandnew1")


def test_reset_code_is_single_use(users_db):
    _make_user("r@acme.com")
    code = auth.request_password_reset("r@acme.com")
    auth.reset_password("r@acme.com", code, "brandnew1")
    with pytest.raises(auth.AuthError):
        auth.reset_password("r@acme.com", code, "anotherpw1")  # already consumed


def test_reset_requires_prior_request(users_db):
    _make_user("r@acme.com")
    with pytest.raises(auth.AuthError):
        auth.reset_password("r@acme.com", "123456", "brandnew1")


# --- mailer ----------------------------------------------------------------
def test_mailer_not_configured_by_default(monkeypatch):
    for var in ("RRD_SMTP_HOST", "RRD_SMTP_USER", "RRD_SMTP_PASSWORD", "RRD_SMTP_FROM"):
        monkeypatch.delenv(var, raising=False)
    assert mailer.smtp_configured() is False
    ok, reason = mailer.send_email("x@y.com", "Hi", "Body")
    assert ok is False and "not configured" in reason.lower()
