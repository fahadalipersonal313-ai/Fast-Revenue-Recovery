"""Smoke test: every Streamlit page renders without raising.

Uses Streamlit's AppTest harness, which executes the script headlessly and
captures any exception — no browser needed. Skipped automatically if the
Streamlit testing API is unavailable.

The app now requires login (multi-tenant isolation, see src/auth.py); this
test signs up a throwaway tenant in a tmp_path-isolated users/tenants
database (never touching the real data/ directory) and injects the resulting
user into session_state before running, so we still exercise every page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

v1 = pytest.importorskip("streamlit.testing.v1")
AppTest = v1.AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def test_login_page_renders_when_logged_out():
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception, f"Login page raised: {at.exception}"
    assert at.tabs  # Log in / Sign up tabs


def test_all_pages_render_without_exception(tmp_path, monkeypatch):
    import src.auth as auth

    monkeypatch.setattr(auth, "USERS_DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "TENANTS_DIR", tmp_path / "tenants")
    user = auth.signup("smoketest@example.com", "testpassword123", "Smoke Co")

    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["user"] = user
    at.run()
    assert not at.exception, f"Landing page raised: {at.exception}"

    # Walk every sidebar page by setting nav_choice and re-running. The sidebar
    # now uses grouped buttons instead of a single radio, so we drive it via
    # session state rather than clicking each button.
    import app as app_module

    for label in list(app_module.PAGES.keys()):
        at.session_state["_pending_nav"] = label
        at.run()
        assert not at.exception, f"Page '{label}' raised: {at.exception}"
