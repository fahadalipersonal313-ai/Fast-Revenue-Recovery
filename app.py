"""Revenue Recovery Desk — Streamlit application entry point.

Run with:  streamlit run app.py

This is an *agent-assisted* tool, not an autonomous one. It reviews invoices,
quotes and leads, recommends and drafts actions, and waits for human approval.
It never sends messages in version one.
"""

from __future__ import annotations

# Route TLS through the OS trust store before any networking import, so HTTPS
# calls work behind antivirus/proxy SSL scanning (see net_bootstrap docstring).
from src.net_bootstrap import enable_os_trust_store

enable_os_trust_store()

import pandas as pd
import streamlit as st

from src import analytics
from src import bulk_invoice as bulk
from src import column_mapper as cm
from src import database as db
from src import email_draft as ed
from src import export_engine as ex
from src import ingest
from src import invoice_generator as ig
from src import mailer
from src import ui
from src.approval_engine import (
    analyze_and_queue,
    approve,
    edit_message,
    list_queue,
    mark_completed,
    postpone,
    reject,
)
from src.ai_helper import (
    ai_available,
    classify_reply,
    message_tone_variants,
)
from src.reply_actions import describe_classification
from src import auth
from src import crypto
from src.config import Settings
from src.memory import AgentMemory
from src.scheduler import RecoveryScheduler, load_active_records, run_daily_analysis
from src.utils import format_currency, today
from datetime import timedelta

st.set_page_config(page_title="Revenue Recovery Desk", page_icon="💰", layout="wide")


# ---------------------------------------------------------------------------
# Authentication gate — every tenant gets their own isolated database.
# ---------------------------------------------------------------------------
def _login_page() -> None:
    ui.inject_theme()
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.markdown(
            "<div class='rrd-auth'><div class='brand'>Revenue Recovery Desk</div>"
            "<div class='tag'>Agent-assisted invoice, quote &amp; lead recovery — "
            "you approve everything.</div></div>",
            unsafe_allow_html=True,
        )
        tab_login, tab_signup, tab_reset = st.tabs(
            ["Log in", "Sign up", "Forgot password"])

        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Log in", type="primary",
                                                  use_container_width=True)
            if submitted:
                try:
                    st.session_state.user = auth.login(email, password)
                    st.rerun()
                except auth.AuthError as exc:
                    st.error(str(exc))

        with tab_signup:
            with st.form("signup_form"):
                company = st.text_input("Company name", key="signup_company")
                email2 = st.text_input("Email", key="signup_email")
                password2 = st.text_input("Password (min 8 characters)", type="password",
                                          key="signup_password")
                submitted2 = st.form_submit_button("Create account", type="primary",
                                                   use_container_width=True)
            if submitted2:
                try:
                    st.session_state.user = auth.signup(email2, password2, company)
                    st.rerun()
                except auth.AuthError as exc:
                    st.error(str(exc))

        with tab_reset:
            if not mailer.smtp_configured():
                st.info(
                    "Password reset by email isn't set up on this server yet. The "
                    "administrator needs to set the `RRD_SMTP_*` environment variables "
                    "(host, user, password, from). Until then, change your password "
                    "from **Settings → Account** while logged in.",
                    icon="✉️",
                )
            else:
                st.caption("We'll email you a 6-digit code to reset your password.")
                with st.form("reset_request_form"):
                    reset_email = st.text_input("Account email", key="reset_email")
                    req = st.form_submit_button("Send reset code",
                                                use_container_width=True)
                if req:
                    code = auth.request_password_reset(reset_email)
                    if code:
                        ok, reason = mailer.send_email(
                            reset_email.strip().lower(),
                            "Your Revenue Recovery Desk reset code",
                            f"Your password reset code is: {code}\n\n"
                            "It expires in 30 minutes. If you didn't request this, "
                            "you can ignore this email.",
                        )
                        if not ok:
                            st.error(f"Couldn't send the email: {reason}")
                    # Same message regardless, so we never reveal which emails exist.
                    if not code or ok:
                        st.success("If that email has an account, a reset code is on "
                                   "its way. Enter it below.")
                    st.session_state["reset_flow_email"] = reset_email.strip().lower()

                if st.session_state.get("reset_flow_email"):
                    with st.form("reset_confirm_form"):
                        code_in = st.text_input("6-digit code", key="reset_code")
                        npw = st.text_input("New password (min 8 characters)",
                                            type="password", key="reset_new_pw")
                        npw2 = st.text_input("Confirm new password", type="password",
                                             key="reset_new_pw2")
                        confirm = st.form_submit_button("Reset password",
                                                        type="primary",
                                                        use_container_width=True)
                    if confirm:
                        if npw != npw2:
                            st.error("The two passwords don't match.")
                        else:
                            try:
                                auth.reset_password(
                                    st.session_state["reset_flow_email"], code_in, npw)
                                st.session_state.pop("reset_flow_email", None)
                                st.success("Password reset! You can now log in with "
                                           "your new password.")
                            except auth.AuthError as exc:
                                st.error(str(exc))


def _require_login() -> auth.User:
    if "user" not in st.session_state:
        _login_page()
        st.stop()
    return st.session_state.user


# ---------------------------------------------------------------------------
# Shared state — every cached/session value below is scoped to the logged-in
# tenant, so one client's data, settings and email credentials never leak
# into another's.
# ---------------------------------------------------------------------------
@st.cache_resource
def _tenant_memory(tenant_slug: str) -> AgentMemory:
    return AgentMemory(path=auth.tenant_db_path(tenant_slug))


def get_memory() -> AgentMemory:
    user = _require_login()
    return _tenant_memory(user.tenant_slug)


def get_settings() -> Settings:
    mem = get_memory()
    if "settings" not in st.session_state:
        st.session_state.settings = mem.load_settings()
    return st.session_state.settings


def get_scheduler() -> RecoveryScheduler:
    if "scheduler" not in st.session_state:
        st.session_state.scheduler = RecoveryScheduler(get_memory(), get_settings())
    return st.session_state.scheduler


def money(amount: float) -> str:
    return format_currency(amount or 0, get_settings().currency_symbol)


def _goto(page_label: str) -> None:
    """Queue a sidebar navigation change to take effect on the next run."""
    st.session_state["_pending_nav"] = page_label
    st.rerun()


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------
_STATUS_FIELD = {"invoice": "payment_status", "quote": "quote_status", "lead": "lead_status"}


def _records_from_df(df: pd.DataFrame, mapping: dict, status_map: dict | None = None,
                     record_type: str = "invoice") -> list[dict]:
    """Apply the mapping (and optional status translation) → list of clean dicts."""
    processed = cm.apply_mapping(df, mapping)
    status_field = _STATUS_FIELD[record_type]
    if status_map and status_field in processed.columns:
        processed[status_field] = cm.apply_status_map(processed[status_field], status_map)
    records = processed.to_dict("records")
    cleaned = []
    for rec in records:
        cleaned.append({k: (None if pd.isna(v) else v) for k, v in rec.items()})
    return cleaned


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _safe_image(path: str, caption: str | None = None) -> None:
    """Render an image if present; silently skip if the assets folder hasn't
    been populated yet. Keeps the welcome page graceful pre-photo-upload."""
    from pathlib import Path as _P
    if _P(path).exists():
        st.image(path, use_container_width=True, caption=caption)


def page_welcome() -> None:
    """Premium onboarding experience — auto-shown on first login, always
    accessible from the sidebar as "✨ Get started" afterwards. Includes a
    live email-credentials form so users finish setup inside the welcome flow
    instead of being told to "go find Settings."
    """
    mem = get_memory()
    settings = get_settings()
    user = _require_login()
    ui.welcome_styles()

    company = user.company_name or "there"
    email_set = bool(settings.email_address and settings.email_app_password)
    ai_on = ai_available(settings)

    # --- Hero (text left, founder photo right) -----------------------------
    hero_col_l, hero_col_r = st.columns([1.35, 1], gap="medium")
    with hero_col_l:
        st.markdown(
            f"""
            <div class="rrd-hero">
              <div class="rrd-hero-orb rrd-orb-1"></div>
              <div class="rrd-hero-orb rrd-orb-2"></div>
              <div class="rrd-hero-orb rrd-orb-3"></div>
              <div class="rrd-hero-inner">
                <div class="rrd-hero-eyebrow">Welcome aboard 🎉</div>
                <h1 class="rrd-hero-title">Hi {company},<br/>let's recover<br/>some revenue.</h1>
                <p class="rrd-hero-sub">
                  Revenue Recovery Desk is your AI-assisted second pair of hands —
                  it reads your invoices, quotes and leads, spots what needs
                  chasing, drafts polite follow-ups, and waits for your green
                  light. <strong>You stay in control. Always.</strong>
                </p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with hero_col_r:
        _safe_image("assets/01-hero-portrait.jpg", caption=None)

    # --- Section 1: What this app can do ----------------------------------
    st.markdown("<div class='rrd-wsec'><div class='rrd-wsec-num'>1</div>"
                "<div class='rrd-wsec-head'>What this app can do</div>"
                "<div class='rrd-wsec-sub'>Three workflows you'll use again and again</div>"
                "</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="rrd-pipes">
          <div class="rrd-pipe rrd-pipe-1">
            <div class="rrd-pipe-glyph">🧮</div>
            <div class="rrd-pipe-step">Step 1</div>
            <h3>Generate invoices</h3>
            <p>Build a clean PDF invoice in 30 seconds — single or bulk from a
               spreadsheet. Auto-saved as an email draft when you're ready.</p>
            <div class="rrd-pipe-tag">Invoices → Generate tab</div>
          </div>
          <div class="rrd-pipe rrd-pipe-2">
            <div class="rrd-pipe-glyph">📤</div>
            <div class="rrd-pipe-step">Step 2</div>
            <h3>Import your data</h3>
            <p>Drop in an Excel or CSV of invoices, quotes or leads. The
               column-mapper learns your client's format the first time —
               every future upload becomes one click.</p>
            <div class="rrd-pipe-tag">Upload</div>
          </div>
          <div class="rrd-pipe rrd-pipe-3">
            <div class="rrd-pipe-glyph">🤖</div>
            <div class="rrd-pipe-step">Step 3</div>
            <h3>Get a recovery plan</h3>
            <p>The agent ranks every record by urgency, drafts a polite
               follow-up, and queues it for your approval. You hit
               <em>Approve</em>, copy the message, send it from your own inbox.</p>
            <div class="rrd-pipe-tag">Approvals · Daily Plan</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        if ui.link_button("Generate an invoice", "🧾 Invoices",
                          key="welc_gen", use_container_width=True):
            _goto("🧾 Invoices")
    with c2:
        if ui.link_button("Upload a file", "📤 Upload",
                          key="welc_upl", use_container_width=True):
            _goto("📤 Upload")
    with c3:
        if ui.link_button("See the daily plan", "🗂️ Daily Plan",
                          key="welc_plan", use_container_width=True):
            _goto("🗂️ Daily Plan")

    # --- Section 2: Connect your email --------------------------------------
    st.markdown("<div class='rrd-wsec'><div class='rrd-wsec-num'>2</div>"
                "<div class='rrd-wsec-head'>Connect your email (2 minutes)</div>"
                "<div class='rrd-wsec-sub'>So every drafted message lands in your "
                "own Drafts folder — nothing is ever sent automatically</div>"
                "</div>", unsafe_allow_html=True)

    badge = ("<span class='rrd-badge rrd-badge-ok'>✓ Connected</span>"
             if email_set else
             "<span class='rrd-badge rrd-badge-todo'>● Not connected yet</span>")
    st.markdown(f"<div class='rrd-status-row'>{badge}"
                f"{'<span class=rrd-status-mail>'+settings.email_address+'</span>' if email_set else ''}"
                f"</div>", unsafe_allow_html=True)

    with st.expander("📧 Step-by-step: connect your Gmail / Workspace", expanded=not email_set):
        st.markdown(
            """
            <div class="rrd-steps">
              <div class="rrd-step">
                <div class="rrd-step-dot">1</div>
                <div class="rrd-step-body">
                  <strong>Turn on 2-Step Verification</strong> on your Google account.
                  Open <a href="https://myaccount.google.com/security" target="_blank">myaccount.google.com/security</a>
                  → click <em>2-Step Verification</em> → finish the wizard. Required before Step 2.
                </div>
              </div>
              <div class="rrd-step">
                <div class="rrd-step-dot">2</div>
                <div class="rrd-step-body">
                  <strong>Generate an App Password.</strong> Go to
                  <a href="https://myaccount.google.com/apppasswords" target="_blank">myaccount.google.com/apppasswords</a>,
                  name it "Revenue Recovery Desk", click <em>Create</em>. Google shows you a
                  <strong>16-character code</strong> (with spaces — paste it as-is, spaces are fine).
                </div>
              </div>
              <div class="rrd-step">
                <div class="rrd-step-dot">3</div>
                <div class="rrd-step-body">
                  <strong>Paste both below and click Connect.</strong> Your app password is
                  encrypted with the app's secret key before being stored — never readable in plain
                  text, never shared with other accounts.
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("welcome_email_form"):
            e_col1, e_col2 = st.columns(2)
            wem_addr = e_col1.text_input(
                "Your email address",
                value=settings.email_address or "",
                placeholder="you@yourcompany.com",
                key="welc_email_addr",
            )
            wem_pw = e_col2.text_input(
                "16-character App Password",
                type="password",
                placeholder="xxxx xxxx xxxx xxxx",
                key="welc_email_pw",
            )
            wem_submit = st.form_submit_button(
                "🔐 Connect email",
                type="primary",
                use_container_width=True,
            )
        if wem_submit:
            if not wem_addr or not wem_pw:
                st.error("Both fields are required.")
            else:
                mem.save_email_credentials(wem_addr.strip(), wem_pw.strip())
                st.session_state.pop("settings", None)  # reload with new creds
                st.success("✓ Email connected. Drafts will be saved to your Drafts folder.")
                st.rerun()

        st.caption(
            "On Outlook / Microsoft 365? Plain-password IMAP is disabled by Microsoft. "
            "OAuth integration is on the roadmap — for now Outlook customers need to "
            "wait until that ships."
        )

    # --- Section 3: AI helper -----------------------------------------------
    st.markdown("<div class='rrd-wsec'><div class='rrd-wsec-num'>3</div>"
                "<div class='rrd-wsec-head'>Your AI helper</div>"
                "<div class='rrd-wsec-sub'>What it does today — and what you control</div>"
                "</div>", unsafe_allow_html=True)

    ai_status_html = (
        "<span class='rrd-badge rrd-badge-ok'>✓ AI is ON</span>"
        if ai_on else
        "<span class='rrd-badge rrd-badge-todo'>● AI is OFF (rules mode)</span>"
    )
    st.markdown(f"<div class='rrd-status-row'>{ai_status_html}"
                f"<span class='rrd-status-mail'>Powered by Google Gemini · free tier</span>"
                f"</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="rrd-ai-cards">
          <div class="rrd-ai-card">
            <div class="rrd-ai-ic">✍️</div>
            <h4>Smarter message drafts</h4>
            <p>The agent rewrites each follow-up in three tones — friendly, firm, and
               urgent — so you pick what fits the customer relationship.</p>
          </div>
          <div class="rrd-ai-card">
            <div class="rrd-ai-ic">🧠</div>
            <h4>Reply intent detection</h4>
            <p>Paste a customer's reply, and the AI classifies it (paying soon,
               disputing, asking for more time…) and suggests your next move.</p>
          </div>
          <div class="rrd-ai-card">
            <div class="rrd-ai-ic">🛡️</div>
            <h4>You stay in control</h4>
            <p>The AI never sends messages and never approves on its own. Every
               action waits for your click. You can turn AI off any time in Settings.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Section 4: Built for teams like yours (photo strip) ---------------
    st.markdown("<div class='rrd-wsec'><div class='rrd-wsec-num'>4</div>"
                "<div class='rrd-wsec-head'>Built for teams like yours</div>"
                "<div class='rrd-wsec-sub'>From solo founders to small ops teams — "
                "we ship the polite-but-firm follow-ups, you keep the relationships</div>"
                "</div>", unsafe_allow_html=True)

    pc1, pc2, pc3 = st.columns(3, gap="medium")
    with pc1:
        _safe_image("assets/05-team-of-three.jpg")
    with pc2:
        _safe_image("assets/06-team-of-four.jpg")
    with pc3:
        _safe_image("assets/08-team-celebration.jpg")

    st.markdown("<div class='rrd-finish'></div>", unsafe_allow_html=True)
    fc1, fc2, fc3 = st.columns([1, 2, 1])
    with fc2:
        if st.button("✨  I'm ready — take me to the app",
                     type="primary", use_container_width=True, key="welc_finish"):
            mem.mark_onboarding_completed()
            _goto("🏠 Home")
        st.caption(
            "You can revisit this guide any time from **✨ Get started** in the sidebar.",
            help=None,
        )


def page_dashboard() -> None:
    mem = get_memory()
    s = analytics.stats(mem)
    ui.page_header("Dashboard", "Your recovery overview at a glance.")

    if not s["has_data"]:
        ui.empty_state(
            "Bring in your first file to get started",
            "Import invoices, quotes or leads in the Upload Center. No file handy? "
            "Load a one-click sample to explore the app with realistic data.",
            icon="📂",
        )
        if st.button("Open Upload Center", type="primary"):
            _goto("📤 Upload")
        return

    ui.section("Money overview")
    ui.kpi_cards([
        {"label": "At risk", "value": money(s["at_risk"]),
         "sub": "Unpaid invoices + open quotes", "accent": "red"},
        {"label": "Recovered", "value": money(s["recovered"]),
         "sub": "Invoices marked paid", "accent": "green"},
        {"label": "Pending approvals", "value": str(s["pending"]),
         "sub": "Waiting for you", "accent": "indigo"},
        {"label": "Due today", "value": str(s["due_today"]),
         "sub": "Follow-ups scheduled", "accent": "amber"},
        {"label": "Overdue", "value": str(s["overdue_tasks"]),
         "sub": "Past-due tasks", "accent": "red"},
    ])

    ui.section("Dive into one area", "Each has its own independent dashboard")
    c1, c2, c3 = st.columns(3)
    if c1.button("🧾 Invoices", use_container_width=True):
        _goto("🧾 Invoices")
    if c2.button("📄 Quotes", use_container_width=True):
        _goto("📄 Quotes")
    if c3.button("🎯 Leads", use_container_width=True):
        _goto("🎯 Leads")

    done = [s["has_data"], s["handled"] > 0, s["completed"] > 0]
    if not all(done):
        ui.section("Getting started")
        ui.checklist([
            ("Import your invoices, quotes or leads", done[0]),
            ("Review and approve items in the queue", done[1]),
            ("Send a message, then mark it completed", done[2]),
        ])

    if s["pending"] > 0:
        ui.section("Next step")
        st.info(f"You have **{s['pending']}** recommendation(s) waiting for your review.")
        if st.button("Go to Approvals", type="primary"):
            _goto("✅ Approvals")

    with st.expander("How this works (30-second version)"):
        st.markdown(
            "**The app never sends messages — you do.** It reviews your records, drafts a "
            "polite message, and waits for your approval.\n\n"
            "1. **Upload Center** — import invoices, quotes or leads, then *Process & analyze*.\n"
            "2. **Approval Queue** — review each item, edit if you like, click **Approve**.\n"
            "3. **Copy the message and send it** from your own WhatsApp or email.\n"
            "4. Click **Mark completed**.\n"
            "5. Got paid or won a deal? Open the matching recovery page and mark the outcome — "
            "no re-upload needed."
        )


def page_upload() -> None:
    mem = get_memory()
    settings = get_settings()
    ui.page_header("Upload Center", "Import any client's invoices, quotes or leads — "
                   "we adapt to their columns, formats and wording.")

    st.info("**Built for many clients.** Each client's file can look totally different. "
            "Map it once, save it as a **profile**, and next time we recognise their layout "
            "and apply it automatically.", icon="🧩")

    st.markdown("##### Step 1 — What are you uploading?")
    record_type = st.selectbox("Record type", ["invoice", "quote", "lead"],
                               format_func=lambda x: {"invoice": "🧾 Invoices",
                               "quote": "📄 Quotes", "lead": "🎯 Leads"}[x])
    col_a, col_b = st.columns([2, 1])
    with col_a:
        uploaded = st.file_uploader("Upload an Excel or CSV file (any layout)",
                                    type=["xlsx", "xls", "csv"])
    with col_b:
        st.markdown("**🎁 No file handy?**")
        if st.button("✨ Load matching sample"):
            from sample_data.generate_samples import generate_all
            from src.config import SAMPLE_DIR
            path = {"invoice": SAMPLE_DIR / "sample_invoices.xlsx",
                    "quote": SAMPLE_DIR / "sample_quotes.xlsx",
                    "lead": SAMPLE_DIR / "sample_leads.xlsx"}[record_type]
            if not path.exists():
                generate_all()
            st.session_state.upload_bytes = path.read_bytes()
            st.session_state.upload_type = record_type
            st.session_state.upload_name = path.name
            st.toast(f"Loaded sample {path.name}", icon="✨")

    if uploaded is not None:
        st.session_state.upload_bytes = uploaded.getvalue()
        st.session_state.upload_type = record_type
        st.session_state.upload_name = uploaded.name

    data = st.session_state.get("upload_bytes")
    if data is None:
        return
    rtype = st.session_state.get("upload_type", record_type)
    fname = st.session_state.get("upload_name", "upload.xlsx")

    # --- Step 2: robust read with sheet / header-row controls ---------------
    st.markdown("##### Step 2 — Read the file")
    info = ingest.inspect(data, fname)
    sheet = None
    c1, c2 = st.columns(2)
    if info.get("kind") == "excel" and info.get("sheets"):
        sheet = c1.selectbox("Worksheet", info["sheets"])
    else:
        c1.caption(f"CSV · delimiter `{info.get('delimiter')}` · {info.get('encoding')}")
    header_mode = c2.radio("Header row", ["Auto-detect", "Set manually"], horizontal=True)
    header_row = None
    if header_mode == "Set manually":
        header_row = c2.number_input("Header is on row #", min_value=1, value=1) - 1

    try:
        df, meta = ingest.read_table(data, fname, sheet=sheet, header_row=header_row)
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read the file: {e}")
        return
    if df.empty:
        st.warning("No data rows found. Try a different sheet or set the header row manually.")
        return
    st.caption(f"Detected header on row {meta.get('header_row', 0) + 1} · {meta.get('rows', 0)} data rows")
    st.dataframe(df.head(15), use_container_width=True)

    # --- Step 3: profile auto-match + mapping -------------------------------
    st.markdown("##### Step 3 — Match the columns")
    profiles = mem.list_mapping_profiles(rtype)
    learned = mem.learned_aliases(rtype)
    matched = cm.match_profile(profiles, list(df.columns))

    prof_names = ["🤖 Auto-detect"] + [f"📁 {p['name']}" for p in profiles]
    default_idx = 0
    if matched:
        default_idx = next((i + 1 for i, p in enumerate(profiles) if p["id"] == matched["id"]), 0)
        st.success(f"✨ This looks like **{matched['name']}** "
                   f"({int(matched['match_score'] * 100)}% header match) — its mapping is pre-filled.")
    chosen = st.selectbox("Use a saved client profile", prof_names, index=default_idx)

    if chosen != "🤖 Auto-detect":
        prof = profiles[prof_names.index(chosen) - 1]
        base_mapping = {k: v for k, v in prof["mapping"].items() if v in df.columns}
        base_status_map = prof.get("status_map", {})
    else:
        base_mapping, _ = cm.detect_mapping(list(df.columns), rtype, learned=learned)
        base_status_map = {}

    fields = list(cm.FIELD_SETS[rtype].keys())
    options = ["(none)"] + list(df.columns)
    final_mapping: dict = {}
    grid = st.columns(2)
    for i, field in enumerate(fields):
        default = base_mapping.get(field, "(none)")
        idx = options.index(default) if default in options else 0
        label = ("✅ " if field in base_mapping else "❔ ") + field
        choice = grid[i % 2].selectbox(label, options, index=idx, key=f"map_{rtype}_{field}")
        if choice != "(none)":
            final_mapping[field] = choice

    missing = cm.missing_required(final_mapping, rtype)
    if missing:
        st.warning(f"⚠️ Please map these required fields: **{', '.join(missing)}**")

    # --- Step 4: status vocabulary mapping ----------------------------------
    status_map: dict = {}
    status_field = _STATUS_FIELD[rtype]
    if status_field in final_mapping:
        with st.expander("🏷️ Status wording (map this client's words to standard ones)", expanded=bool(matched is None)):
            raw_vals = sorted({str(v).strip() for v in df[final_mapping[status_field]].dropna().unique()
                               if str(v).strip()})
            suggested = cm.suggest_status_map(raw_vals, rtype)
            cats = ["(leave as-is)"] + cm.STATUS_CATEGORIES[rtype]
            st.caption("We guessed these. Adjust any that are wrong so the agent reads them correctly.")
            sgrid = st.columns(2)
            for i, val in enumerate(raw_vals):
                guess = base_status_map.get(cm._norm(val)) or suggested.get(cm._norm(val), "")
                sidx = cats.index(guess) if guess in cats else 0
                pick = sgrid[i % 2].selectbox(f"“{val}” →", cats, index=sidx, key=f"st_{rtype}_{val}")
                if pick != "(leave as-is)":
                    status_map[val] = pick

    # --- Step 5: save profile + analyze -------------------------------------
    st.markdown("##### Step 4 — Save & analyze")
    sc1, sc2 = st.columns([2, 1])
    profile_name = sc1.text_input("Save this layout as a client profile (optional)",
                                  value=(matched["name"] if matched else ""),
                                  placeholder="e.g. Acme Ltd — monthly invoices")
    remember = sc2.checkbox("Teach the detector", value=True,
                            help="Remember these column names to improve auto-detection for all clients.")

    if st.button("Process & analyze", type="primary", disabled=bool(missing)):
        if profile_name.strip():
            mem.save_mapping_profile(
                profile_name.strip(), rtype, final_mapping,
                signature=cm.header_signature(list(df.columns)),
                status_map=status_map, sheet_name=sheet or "",
                header_row=meta.get("header_row", 0),
            )
        if remember:
            mem.learn_aliases(rtype, final_mapping)
        records = _records_from_df(df, final_mapping, status_map, rtype)
        db.execute(
            "INSERT INTO uploads(record_type, filename, row_count, original_json) VALUES (?,?,?,?)",
            (rtype, fname, len(df), df.to_json(orient="records")), path=mem.path,
        )
        plan = analyze_and_queue(mem, settings, {rtype: records})
        st.session_state.last_plan = plan
        st.success(f"Processed **{len(records)}** {rtype} records into **{len(plan)}** recommendations."
                   + (f" Saved profile **{profile_name.strip()}**." if profile_name.strip() else ""))
        st.info("Next stop → **Approval Queue** to review and approve.")


def page_daily_plan() -> None:
    mem = get_memory()
    settings = get_settings()
    ui.page_header("Daily Recovery Plan",
                   "Everyone who needs a nudge, ranked by urgency — your to-do list for the day.")

    if st.button("🔄 Rebuild plan from current data"):
        summary = run_daily_analysis(mem, settings)
        st.session_state.last_plan = analyze_and_queue(mem, settings, load_active_records(mem), enqueue=False)
        st.toast(f"Reviewed {summary['plan_items']} items ({summary['high_priority']} high priority)", icon="✅")

    plan = st.session_state.get("last_plan")
    if not plan:
        st.info("No plan yet. Upload data in **Upload Center**, then rebuild the plan here.")
        return

    frame = ex.daily_plan_frame(plan)
    st.dataframe(frame, use_container_width=True, height=440)
    st.download_button("⬇️ Export plan to Excel", ex.to_excel_bytes({"Daily Recovery Plan": frame}),
                       file_name="daily_recovery_plan.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Outcome controls per record type ------------------------------------------
_OUTCOME_ACTIONS = {
    "invoice": [("💰 Mark Paid", "Paid", "recovered", True),
                ("❌ Write off (lost)", "Written off", "lost", False)],
    "quote": [("🎉 Mark Won", "Accepted", "won", True),
              ("👋 Mark Lost", "Lost", "lost", False)],
    "lead": [("🌟 Mark Converted", "Won", "converted", True),
             ("👋 Mark Lost", "Lost", "lost", False)],
}


# Per-type pipeline pages — one page per record type, tabs inside instead of
# separate "Dashboard" and "Recovery" nav items. Each tab is filtered to that
# record_type only; no totals or queue counts are shared across types.
_PIPELINE = {
    "invoice": {
        "title": "Invoices", "icon": "🧾",
        "tagline": "Money owed, money recovered — your invoice pipeline in one place.",
        "open_label": "Unpaid value", "closed_word": "Paid",
    },
    "quote": {
        "title": "Quotes", "icon": "📄",
        "tagline": "Open pipeline value and win rate — quotes only.",
        "open_label": "Open value", "closed_word": "Won",
    },
    "lead": {
        "title": "Leads", "icon": "🎯",
        "tagline": "Open pipeline and conversions — leads only.",
        "open_label": "Open value", "closed_word": "Converted",
    },
}


def _render_pipeline_overview(record_type: str) -> None:
    cfg = _PIPELINE[record_type]
    mem = get_memory()
    s = analytics.type_stats(mem, record_type)
    if not s["has_data"]:
        ui.empty_state(
            f"No {record_type}s yet",
            f"Import {record_type}s in the Upload Center to see this dashboard fill in.",
            icon=cfg["icon"],
        )
        if st.button("Open Upload Center", type="primary", key=f"empty_upload_{record_type}"):
            _goto("📤 Upload")
        return

    ui.kpi_cards([
        {"label": cfg["open_label"], "value": money(s["open_value"]),
         "sub": f"{s['open_count']} open", "accent": "amber"},
        {"label": cfg["closed_word"], "value": money(s["closed_value"]),
         "sub": f"{s['closed_count']} {cfg['closed_word'].lower()}", "accent": "green"},
        {"label": "Pending approvals", "value": str(s["pending_approvals"]),
         "sub": "Waiting for you", "accent": "indigo"},
        {"label": "Due today", "value": str(s["due_today"]), "accent": "blue"},
        {"label": "Overdue", "value": str(s["overdue_tasks"]), "accent": "red"},
    ])
    breakdown = analytics.status_breakdown(mem, record_type)
    if breakdown:
        ui.section("By status")
        st.dataframe(pd.DataFrame(breakdown), use_container_width=True, hide_index=True)
    if record_type == "invoice":
        aging = analytics.aging_buckets(mem)
        ui.section("Unpaid invoices by age")
        st.dataframe(pd.DataFrame(aging), use_container_width=True, hide_index=True)


def _render_pipeline_recommendations(record_type: str) -> None:
    mem = get_memory()
    recs = db.query(
        "SELECT customer_name, reference, amount, priority, priority_score, action, reason, stage "
        "FROM recommendations WHERE record_type=? ORDER BY priority_score DESC",
        (record_type,), path=mem.path,
    )
    if not recs:
        st.info(f"No {record_type} recommendations yet. Upload data and click "
                "**Process & analyze** in the Upload page to generate them.")
        return
    st.caption(f"What the agent suggests for your {record_type}s, highest priority first. "
               "Approve, edit or postpone each one in the Approvals page.")
    st.dataframe(pd.DataFrame(recs), use_container_width=True, hide_index=True)
    if st.button("Open Approvals", type="primary", key=f"recs_goto_approvals_{record_type}"):
        _goto("✅ Approvals")


def _render_pipeline_records(record_type: str) -> None:
    mem = get_memory()
    records = mem.open_records(record_type)

    ui.section("Update an outcome", "No re-upload needed")
    if not records:
        st.info("No records yet — add some in **Upload**.")
    else:
        labels = {f"{r['reference'] or '—'} · {r['customer_name']} · {money(r['amount'])} "
                  f"[{r['status'] or 'open'}]": (r["reference"], r["customer_name"])
                  for r in records}
        pick = st.selectbox("Choose a record", list(labels.keys()), key=f"oc_pick_{record_type}")
        ref, cust = labels[pick]
        cols = st.columns(len(_OUTCOME_ACTIONS[record_type]))
        for i, (btn, status, outcome, celebrate) in enumerate(_OUTCOME_ACTIONS[record_type]):
            if cols[i].button(btn, key=f"oc_{record_type}_{i}"):
                mem.update_record_outcome(record_type, ref, cust, status, outcome)
                if celebrate:
                    st.success(f"Marked **{cust}** as {status}. The queue has been tidied.")
                else:
                    st.toast(f"{cust} marked {status}.", icon="👋")
                st.rerun()

    ui.section("Stored records")
    frame = ex.records_frame(mem, record_type)
    if frame.empty:
        st.caption("Nothing here yet.")
    else:
        st.dataframe(frame, use_container_width=True)


def page_invoices() -> None:
    cfg = _PIPELINE["invoice"]
    ui.page_header(cfg["title"], cfg["tagline"], icon=cfg["icon"])
    tabs = st.tabs(["📊 Overview", "🤖 Recommendations", "📋 Records", "🧮 Generate"])
    with tabs[0]:
        _render_pipeline_overview("invoice")
    with tabs[1]:
        _render_pipeline_recommendations("invoice")
    with tabs[2]:
        _render_pipeline_records("invoice")
    with tabs[3]:
        gen_single, gen_bulk = st.tabs(["✍️ Single invoice", "📦 Bulk from file"])
        with gen_single:
            _render_single_invoice()
        with gen_bulk:
            _render_bulk_invoices()


def page_quotes() -> None:
    cfg = _PIPELINE["quote"]
    ui.page_header(cfg["title"], cfg["tagline"], icon=cfg["icon"])
    tabs = st.tabs(["📊 Overview", "🤖 Recommendations", "📋 Records"])
    with tabs[0]:
        _render_pipeline_overview("quote")
    with tabs[1]:
        _render_pipeline_recommendations("quote")
    with tabs[2]:
        _render_pipeline_records("quote")


def page_leads() -> None:
    cfg = _PIPELINE["lead"]
    ui.page_header(cfg["title"], cfg["tagline"], icon=cfg["icon"])
    tabs = st.tabs(["📊 Overview", "🤖 Recommendations", "📋 Records"])
    with tabs[0]:
        _render_pipeline_overview("lead")
    with tabs[1]:
        _render_pipeline_recommendations("lead")
    with tabs[2]:
        _render_pipeline_records("lead")


def page_approvals() -> None:
    mem = get_memory()
    settings = get_settings()
    ui.page_header("Approval Queue",
                   "Review, approve, then send it yourself and mark it done.")

    st.info("**The 4 steps:** ① review & edit the message → ② click **Approve** → "
            "③ **copy it and send from your own WhatsApp/email** → ④ click **Mark completed**. "
            "The app never sends for you.", icon="ℹ️")

    if st.session_state.pop("just_approved", None):
        st.success("✅ Approved & scheduled! Now **copy the message below and send it yourself**, "
                   "then click **Mark completed**.")
    if st.session_state.pop("just_drafted", None):
        st.success("📧 Draft saved to your email Drafts folder.")
    draft_failed_reason = st.session_state.pop("draft_failed_reason", None)
    if draft_failed_reason:
        st.warning(f"📧 Could not save the email draft: {draft_failed_reason}")

    s = analytics.stats(mem)
    st.caption(f"{s['handled']} of {s['total_items'] or 0} recommendations handled.")

    status_filter = st.selectbox("Show", ["pending", "all", "approved", "rejected", "postponed", "completed"])
    items = list_queue(mem, None if status_filter == "all" else status_filter)
    if not items:
        st.info("Nothing to show for this filter — you're all caught up.")
        return

    for item in items:
        pr = (item["priority"] or "none").lower()
        title = f"{ui.PRIORITY_EMOJI.get(pr,'⚪')} {item['customer_name']} · {money(item['amount'])} · {item['record_type']}"
        with st.expander(title, expanded=(status_filter == "pending" and item is items[0])):
            st.markdown(ui.priority_chip(pr), unsafe_allow_html=True)
            st.write(f"**Reference:** {item['reference'] or '—'}")
            st.write(f"**Why:** {item['reason']}")
            st.write(f"**Recommended action:** {item['recommended_action']}")
            st.write(f"**Next follow-up:** {item['next_follow_up_date'] or '—'}")
            if item["requires_approval"]:
                st.warning("🔒 Needs your approval before any contact (high-value / sensitive / disputed).")

            # Apply a chosen tone variant BEFORE the widget is instantiated —
            # Streamlit forbids writing a widget's session_state key after it
            # has been created in the same run.
            msg_key = f"msg_{item['id']}"
            pending_key = f"apply_msg_{item['id']}"
            if pending_key in st.session_state:
                st.session_state[msg_key] = st.session_state.pop(pending_key)

            edited = st.text_area("✏️ Message (edit freely)", item["suggested_message"] or "",
                                  key=msg_key, height=150)
            st.caption("📋 Copy-ready version — click the copy icon in its top-right corner:")
            st.code(edited or item["suggested_message"] or "", language="text")
            st.caption("👉 After approving, copy this and send it yourself, then **Mark completed**.")

            # --- AI tone variants: rewrite the message gentle / neutral / firm ---
            if ai_available(settings):
                vkey = f"variants_{item['id']}"
                if st.button("✨ Suggest tone variants (gentle / neutral / firm)",
                             key=f"tv_{item['id']}"):
                    with st.spinner("Generating tone variants…"):
                        variants = message_tone_variants(edited or item["suggested_message"] or "", settings)
                    if variants:
                        st.session_state[vkey] = variants
                    else:
                        st.session_state[vkey] = {}
                        st.warning("Couldn't generate variants right now — the free AI tier may be "
                                   "rate-limited (try again in a minute) or out of today's quota. "
                                   "The message above still works.")
                variants = st.session_state.get(vkey)
                if variants:
                    tabs = st.tabs([f"{t.capitalize()}" for t in variants])
                    for tab, (tone, text) in zip(tabs, variants.items()):
                        with tab:
                            st.write(text)
                            if st.button(f"Use {tone} version", key=f"use_{tone}_{item['id']}"):
                                # Defer the write to the next run, before the
                                # text widget is instantiated (see above).
                                st.session_state[pending_key] = text
                                st.session_state.pop(vkey, None)
                                st.rerun()

            if settings.email_draft_active:
                known_email = mem.get_customer_email(item["customer_name"])
                email_override = st.text_input(
                    "📧 Customer email (used to save the draft)", known_email,
                    key=f"email_{item['id']}",
                    help="Auto-filled if known. Add or correct it here if missing — "
                         "it will be remembered for next time.",
                )
            else:
                email_override = ""

            # --- AI reply-intent detection: paste the customer's reply, get advice ---
            if ai_available(settings):
                with st.popover("📩 Customer replied? Analyze it"):
                    reply_text = st.text_area(
                        "Paste the customer's reply", "",
                        key=f"reply_{item['id']}", height=120,
                    )
                    rkey = f"reply_result_{item['id']}"
                    if st.button("🔍 Analyze reply", key=f"anlz_{item['id']}"):
                        if reply_text.strip():
                            with st.spinner("Reading the reply…"):
                                result = classify_reply(reply_text, settings)
                            st.session_state[rkey] = describe_classification(result)
                        else:
                            st.session_state[rkey] = None
                    advice = st.session_state.get(rkey)
                    if advice:
                        label = advice["intent"].replace("_", " ").title()
                        conf = int(advice["confidence"] * 100)
                        st.markdown(f"**Detected intent:** {label}  ·  {conf}% confidence")
                        if advice.get("summary"):
                            st.caption(f"Summary: {advice['summary']}")
                        if advice.get("promised_date"):
                            st.markdown(f"**Promised date:** {advice['promised_date']}")
                        tone = advice.get("tone")
                        msg = f"**Suggested next step:** {advice['action']}"
                        if advice.get("needs_human"):
                            st.warning(msg + "\n\n🔒 A human should handle this one.")
                        elif tone == "positive":
                            st.success(msg)
                        else:
                            st.info(msg)
                        st.caption("AI only read the reply — Python chose this advice. "
                                   "Nothing was sent or changed.")

            b = st.columns(5)
            if b[0].button("✅ Approve", key=f"ap_{item['id']}"):
                if settings.email_draft_active and email_override.strip():
                    mem.upsert_customer(item["customer_name"], email_override.strip())
                result = approve(mem, item["id"], edited, settings=get_settings())
                st.session_state["just_approved"] = True
                if result.get("email_draft"):
                    st.session_state["just_drafted"] = True
                elif settings.email_draft_active:
                    st.session_state["draft_failed_reason"] = result.get("email_draft_reason")
                st.rerun()
            if b[1].button("✖️ Reject", key=f"rj_{item['id']}"):
                reject(mem, item["id"], "Rejected by user")
                st.toast("Rejected.", icon="✖️")
                st.rerun()
            if b[2].button("💾 Save edit", key=f"ed_{item['id']}"):
                edit_message(mem, item["id"], edited)
                st.toast("Message saved.", icon="💾")
                st.rerun()
            new_date = b[3].date_input("Postpone to", value=today(), key=f"pp_{item['id']}")
            if b[3].button("⏳ Postpone", key=f"ppb_{item['id']}"):
                postpone(mem, item["id"], new_date)
                st.rerun()
            if b[4].button("🏁 Mark completed", key=f"cp_{item['id']}"):
                mark_completed(mem, item["id"], "Completed by user")
                st.toast("Marked completed.", icon="🏁")
                st.rerun()


def page_customer_history() -> None:
    mem = get_memory()
    ui.page_header("Customer History",
                   "Every record, message and decision for any customer, in one place.")
    customers = mem.all_customers()
    if not customers:
        st.info("No customers yet — upload some data first.")
        return
    customer = st.selectbox("Customer", customers)
    hist = mem.customer_history(customer)
    tabs = st.tabs(["📋 Records", "🤖 Recommendations", "✉️ Messages", "✅ Approvals"])
    for tab, key in zip(tabs, ["records", "recommendations", "messages", "approvals"]):
        with tab:
            rows = hist[key]
            st.dataframe(pd.DataFrame(rows), use_container_width=True) if rows else st.caption("Nothing here.")


def page_reports() -> None:
    mem = get_memory()
    ui.page_header("Saved Reports", "Download polished Excel reports for your records or accountant.")
    builders = {
        "📋 Approval queue": lambda: ex.to_excel_bytes({"Approvals": ex.approvals_frame(mem)}),
        "✉️ Message history": lambda: ex.to_excel_bytes({"Messages": ex.messages_frame(mem)}),
        "🧾 Invoice report": lambda: ex.to_excel_bytes({"Invoices": ex.records_frame(mem, "invoice")}),
        "📄 Quote report": lambda: ex.to_excel_bytes({"Quotes": ex.records_frame(mem, "quote")}),
        "🎯 Lead report": lambda: ex.to_excel_bytes({"Leads": ex.records_frame(mem, "lead")}),
        "📝 Decision log": lambda: ex.to_excel_bytes({"Decisions": ex.decision_log_frame(mem)}),
        "📦 Combined report": lambda: ex.combined_report(mem),
    }
    cols = st.columns(2)
    for i, (label, builder) in enumerate(builders.items()):
        cols[i % 2].download_button(label, builder(),
            file_name=label.split(" ", 1)[1].lower().replace(" ", "_") + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_{i}")
    st.divider()
    st.markdown("##### 🕒 Recent activity")
    log = mem.decision_log(100)
    st.dataframe(pd.DataFrame(log), use_container_width=True) if log else st.caption("No activity yet.")


def page_settings() -> None:
    mem = get_memory()
    settings = get_settings()
    sched = get_scheduler()
    user = _require_login()
    ui.page_header("Settings", "Company details, rules, AI, email drafts and the optional daily run.")

    with st.expander("👤 Account & security (your login email and password)"):
        st.caption(f"Signed in as **{user.email}**. Changing your email keeps all your "
                   "data — only the login address changes.")
        ac1, ac2 = st.columns(2)
        with ac1:
            st.markdown("**Change email**")
            with st.form("change_email_form"):
                ce_new = st.text_input("New email", value=user.email, key="ce_new_email")
                ce_pw = st.text_input("Current password", type="password", key="ce_pw")
                ce_go = st.form_submit_button("Update email", use_container_width=True)
            if ce_go:
                try:
                    st.session_state.user = auth.change_email(user.id, ce_pw, ce_new)
                    st.success("Email updated.")
                except auth.AuthError as exc:
                    st.error(str(exc))
        with ac2:
            st.markdown("**Change password**")
            with st.form("change_pw_form"):
                cp_cur = st.text_input("Current password", type="password", key="cp_cur")
                cp_new = st.text_input("New password (min 8)", type="password", key="cp_new")
                cp_new2 = st.text_input("Confirm new password", type="password", key="cp_new2")
                cp_go = st.form_submit_button("Update password", use_container_width=True)
            if cp_go:
                if cp_new != cp_new2:
                    st.error("The two passwords don't match.")
                else:
                    try:
                        auth.change_password(user.id, cp_cur, cp_new)
                        st.success("Password updated.")
                    except auth.AuthError as exc:
                        st.error(str(exc))

    with st.form("settings_form"):
        st.markdown("##### 🏢 Your business")
        company = st.text_input("Company name", settings.company_name)
        signature = st.text_area("Message signature", settings.message_signature)
        c1, c2 = st.columns(2)
        currency = c1.text_input("Currency code", settings.default_currency)
        symbol = c2.text_input("Currency symbol", settings.currency_symbol)
        st.markdown("##### 📏 Rules")
        threshold = st.number_input("High-value approval threshold", value=float(settings.high_value_threshold), step=500.0)
        daily_time = st.text_input("Daily analysis time (HH:MM)", settings.daily_analysis_time)
        c3, c4, c5 = st.columns(3)
        inv_int = c3.number_input("Invoice follow-up days", value=settings.invoice_follow_up_days, min_value=1)
        q_int = c4.number_input("Quote follow-up days", value=settings.quote_follow_up_days, min_value=1)
        l_int = c5.number_input("Lead follow-up days", value=settings.lead_follow_up_days, min_value=1)
        ai_enabled = st.checkbox("🤖 Enable AI message polishing", value=settings.ai_enabled)
        provider_options = ["gemini", "anthropic"]
        provider_index = provider_options.index(settings.ai_provider) if settings.ai_provider in provider_options else 0
        ai_provider = st.selectbox(
            "AI provider", provider_options, index=provider_index,
            help="Gemini has a free tier (recommended). Anthropic requires a paid key.",
        )
        st.caption("The AI key is read only from GEMINI_API_KEY / ANTHROPIC_API_KEY / AI_API_KEY "
                   "environment variables — never stored here.")
        email_draft_enabled = st.checkbox(
            "📧 Save a draft email when I approve an item", value=settings.email_draft_enabled,
            help="Add your email credentials below to turn this on.",
        )
        saved = st.form_submit_button("💾 Save settings")

    if saved:
        settings.company_name = company
        settings.message_signature = signature
        settings.default_currency = currency
        settings.currency_symbol = symbol
        settings.high_value_threshold = float(threshold)
        settings.daily_analysis_time = daily_time
        settings.invoice_follow_up_days = int(inv_int)
        settings.quote_follow_up_days = int(q_int)
        settings.lead_follow_up_days = int(l_int)
        settings.ai_enabled = bool(ai_enabled)
        settings.ai_provider = ai_provider
        settings.email_draft_enabled = bool(email_draft_enabled)
        mem.save_settings(settings)
        st.session_state.settings = settings
        st.toast("Settings saved!", icon="💾")

    st.divider()
    st.markdown("##### 🤖 AI status")
    if ai_available(settings):
        st.success(f"AI is active — provider: **{settings.ai_provider}**, "
                    f"model: **{settings.ai_model_resolved}**.")
    elif settings.ai_enabled and not settings.ai_api_key:
        key_var = "GEMINI_API_KEY" if settings.ai_provider == "gemini" else "ANTHROPIC_API_KEY"
        st.warning(f"AI is enabled but no {key_var} (or AI_API_KEY) is set — "
                   "running on reliable templates.")
    else:
        st.info("AI is off. The app uses reliable built-in templates (perfectly fine!).")

    st.divider()
    st.markdown("##### 📧 Email draft status")
    if settings.email_draft_active:
        st.success(f"Email drafting is active — approving an item saves a draft to "
                    f"**{settings.email_address}**'s Drafts folder.")
    elif settings.email_draft_enabled:
        st.warning("Email drafting is enabled but no email credentials are saved yet — "
                   "add them below.")
    else:
        st.info("Email drafting is off. Enable it above and add your email credentials "
                "below to save a draft on every approval.")

    with st.expander("✏️ Add / update your email credentials"):
        st.caption("Stored encrypted in your own account data — never shared with other "
                   "tenants, never sent anywhere except your own email provider.")
        st.caption("For Gmail: enable 2-Step Verification, then create an "
                   "**App Password** (Google Account → Security → App passwords) — "
                   "do not use your normal Gmail password.")
        with st.form("email_creds_form"):
            cur_address, _ = mem.load_email_credentials()
            new_address = st.text_input("Your email address", cur_address)
            new_app_password = st.text_input(
                "App password", type="password",
                help="Leave blank to keep the currently saved password.",
            )
            ec1, ec2 = st.columns(2)
            save_creds = ec1.form_submit_button("💾 Save email credentials")
            clear_creds = ec2.form_submit_button("🗑️ Remove saved credentials")
        if save_creds:
            if not new_address.strip():
                st.error("Email address is required.")
            elif not new_app_password.strip() and not cur_address:
                st.error("App password is required for a new account.")
            else:
                mem.save_email_credentials(
                    new_address.strip(),
                    new_app_password.strip() or mem.load_email_credentials()[1],
                )
                st.session_state.pop("settings", None)
                st.toast("Email credentials saved.", icon="📧")
                st.rerun()
        if clear_creds:
            mem.clear_email_credentials()
            st.session_state.pop("settings", None)
            st.toast("Email credentials removed.", icon="🗑️")
            st.rerun()

    st.divider()
    st.markdown("##### ⏰ Scheduled daily analysis")
    if not sched.available():
        st.info("APScheduler not installed — run analysis manually from the Daily Recovery Plan page.")
    else:
        c1, c2, c3 = st.columns(3)
        if c1.button("▶️ Start scheduler"):
            sched.reschedule(settings.daily_analysis_time)
            st.toast("Scheduler started.", icon="▶️")
        if c2.button("⏹️ Stop scheduler"):
            sched.shutdown()
            st.toast("Scheduler stopped.", icon="⏹️")
        if c3.button("⚡ Run now"):
            summary = run_daily_analysis(mem, settings)
            st.toast(f"Ran analysis: {summary['plan_items']} items.", icon="⚡")
        st.caption(f"Next scheduled run: {sched.next_run_time() or 'not scheduled'}")


def page_profiles() -> None:
    mem = get_memory()
    ui.page_header("Client Mapping Profiles", "Saved column layouts per client — "
                   "recognised and applied automatically when their file arrives.")

    st.markdown("Profiles are created in **Upload Center** — map a file, give it a name, and "
                "tick *save*. They show up here to review or remove.")

    profiles = mem.list_mapping_profiles()
    if not profiles:
        st.info("No profiles yet. Upload a client's file in **Upload Center**, set the mapping, "
                "and save it with the client's name.")
        return

    learned = {rt: mem.learned_aliases(rt) for rt in ("invoice", "quote", "lead")}
    for p in profiles:
        icon = {"invoice": "🧾", "quote": "📄", "lead": "🎯"}.get(p["record_type"], "📁")
        with st.expander(f"{icon} {p['name']}  ·  {p['record_type']}"):
            st.write("**Column mapping:**")
            st.dataframe(pd.DataFrame(
                [{"Our field": k, "Their column": v} for k, v in p["mapping"].items()]),
                use_container_width=True, hide_index=True)
            if p.get("status_map"):
                st.write("**Status wording:**")
                st.dataframe(pd.DataFrame(
                    [{"Their word": k, "Means": v} for k, v in p["status_map"].items()]),
                    use_container_width=True, hide_index=True)
            st.caption(f"Updated {p.get('updated_at', '')}")
            if st.button("🗑️ Delete profile", key=f"delp_{p['id']}"):
                mem.delete_mapping_profile(p["id"])
                st.toast("Profile deleted.", icon="🗑️")
                st.rerun()

    total_learned = sum(len(v) for d in learned.values() for v in d.values())
    st.divider()
    st.caption(f"🧠 The detector has learned **{total_learned}** column aliases from your "
               f"confirmed mappings — improving auto-detection for every future upload.")


# ---------------------------------------------------------------------------
# Invoice Generator (Phase 2 — manual form → PDF → Gmail draft, per-customer
# profiles you can reload from a dropdown)
# ---------------------------------------------------------------------------
# The form widgets are driven through session_state keys so that "Load profile"
# can pre-fill them. ``_IG_TEXT_DEFAULTS`` covers the plain text fields; the
# line-item table and dates are seeded separately because they aren't strings.
_IG_TEXT_DEFAULTS = {
    "ig_from_company": "company_name",     # value pulled from settings attr
    "ig_from_email": "email_address",
    "ig_from_address": "",
    "ig_customer_name": "",
    "ig_customer_email": "",
    "ig_customer_address": "",
    "ig_invoice_number": "",
    "ig_currency": "currency_symbol",
    "ig_subject": "",
    "ig_body": "",
    "ig_notes": "",
}


def _default_line_items() -> pd.DataFrame:
    return pd.DataFrame([{"Description": "", "Quantity": 1.0, "Unit price": 0.0}])


def _seed_invoice_defaults(settings: Settings) -> None:
    """Populate session_state widget keys once, so the form has sensible
    starting values and ``Load profile`` can later overwrite them."""
    ss = st.session_state
    if ss.get("_ig_seeded"):
        return
    settings_map = {"company_name": settings.company_name or "",
                    "email_address": settings.email_address or "",
                    "currency_symbol": settings.currency_symbol or "$"}
    for key, source in _IG_TEXT_DEFAULTS.items():
        ss.setdefault(key, settings_map.get(source, source))
    ss.setdefault("ig_tax_rate", 0.0)
    ss.setdefault("ig_issue_date", today())
    ss.setdefault("ig_due_date", today())
    ss.setdefault("ig_items_src", _default_line_items())
    ss.setdefault("ig_items_version", 0)
    ss["_ig_seeded"] = True


def _apply_invoice_profile(schema: dict) -> None:
    """Copy a saved profile's fields into the form's session_state keys, then
    bump the data-editor version so the line-item table resets to the profile's
    items. Caller reruns afterwards."""
    ss = st.session_state
    for key in ("ig_from_company", "ig_from_email", "ig_from_address",
                "ig_customer_name", "ig_customer_email", "ig_customer_address",
                "ig_currency", "ig_notes"):
        if key in schema:
            ss[key] = schema[key]
    if "tax_rate" in schema:
        ss["ig_tax_rate"] = float(schema.get("tax_rate") or 0.0)
    items = schema.get("line_items") or []
    if items:
        ss["ig_items_src"] = pd.DataFrame(items)
    ss["ig_items_version"] = ss.get("ig_items_version", 0) + 1


def _collect_profile_schema() -> dict:
    """Snapshot the reusable parts of the current form (everything except the
    per-invoice number/dates) for saving as a customer's invoice format."""
    ss = st.session_state
    src = ss.get("ig_items_src")
    items = src.to_dict("records") if isinstance(src, pd.DataFrame) else []
    return {
        "from_company": ss.get("ig_from_company", ""),
        "from_email": ss.get("ig_from_email", ""),
        "from_address": ss.get("ig_from_address", ""),
        "customer_name": ss.get("ig_customer_name", ""),
        "customer_email": ss.get("ig_customer_email", ""),
        "customer_address": ss.get("ig_customer_address", ""),
        "currency": ss.get("ig_currency", "$"),
        "tax_rate": float(ss.get("ig_tax_rate", 0.0) or 0.0),
        "line_items": items,
        "notes": ss.get("ig_notes", ""),
    }


def _track_invoice(mem, settings, data: ig.InvoiceData, reminder_date=None) -> None:
    """Add a generated invoice to the recovery pipeline: persist it as an open
    invoice record and run the agents so it joins the Daily Recovery Plan and
    (when a reminder is due) the Approval Queue. Re-running for the same invoice
    number updates the existing record rather than duplicating it."""
    record = ig.to_record(data, scheduled_reminder_date=reminder_date)
    analyze_and_queue(mem, settings, {"invoice": [record]})


def _show_single_result(settings) -> None:
    """Render the outcome of the most recent single-invoice generation
    (download + draft status), surviving the rerun the dialog triggers."""
    res = st.session_state.get("ig_result_single")
    if not res:
        return
    if res.get("error"):
        st.error(res["error"])
        st.session_state.pop("ig_result_single", None)
        return
    st.success(f"Invoice rendered · total {format_currency(res['total'], settings)}")
    if res.get("reminder_date"):
        st.info(f"⏰ Reminder set for **{res['reminder_date']}** — this invoice is now "
                "in your Daily Recovery Plan, and on that date it'll appear in the "
                "Approval Queue for you to send a follow-up.")
    else:
        st.caption("Invoice added to your records — no reminder scheduled.")
    cdl, cdr = st.columns(2)
    cdl.download_button("⬇️ Download PDF", res["pdf"], file_name=res["filename"],
                        mime="application/pdf", use_container_width=True,
                        key="ig_single_dl")
    if res.get("draft_ok") is True:
        cdr.success("Draft saved to your email Drafts folder.")
    elif res.get("draft_ok") is False:
        cdr.warning(f"Couldn't save draft: {res.get('draft_reason')}")
    else:
        cdr.caption("Email drafting off — PDF downloaded only.")
    if res.get("save_profile"):
        st.caption(f"💾 Saved **{res['customer']}**'s invoice format — reload it any "
                   "time from the dropdown above.")


def _finalize_single(mem, settings, reminder_date) -> None:
    """Do the real work after the reminder pop-up is answered: render the PDF,
    track the invoice, log it, and save the email draft."""
    p = st.session_state.get("ig_pending_single")
    if not p:
        return
    data: ig.InvoiceData = p["data"]
    try:
        pdf = ig.render_invoice_pdf(data)
    except ig.InvoiceError as exc:
        st.session_state["ig_result_single"] = {"error": str(exc)}
        st.session_state.pop("ig_pending_single", None)
        return

    filename = ig.suggest_filename(data)
    totals = ig.compute_totals(data)

    if p["save_profile"] and p.get("profile_schema") is not None:
        mem.save_invoice_profile(data.customer_name, p["profile_schema"])
    mem.record_generated_invoice(
        customer_name=data.customer_name, invoice_number=data.invoice_number,
        amount=totals["total"], currency=data.currency_symbol,
        source="manual", pdf_filename=filename,
    )
    _track_invoice(mem, settings, data, reminder_date)

    draft_ok = None
    draft_reason = ""
    if ed.email_draft_available(settings):
        draft_ok, draft_reason = ed.save_draft_with_attachment(
            settings=settings, to_addr=p["customer_email"],
            subject=p["email_subject"], body=p["email_body"],
            attachment_bytes=pdf, attachment_filename=filename,
            attachment_mime="application/pdf",
        )

    st.session_state["ig_result_single"] = {
        "pdf": pdf, "filename": filename, "total": totals["total"],
        "customer": data.customer_name, "save_profile": p["save_profile"],
        "reminder_date": reminder_date.isoformat() if reminder_date else None,
        "draft_ok": draft_ok, "draft_reason": draft_reason,
    }
    st.session_state.pop("ig_pending_single", None)


@st.dialog("Schedule a payment reminder?")
def _single_reminder_dialog() -> None:
    mem, settings = get_memory(), get_settings()
    p = st.session_state.get("ig_pending_single")
    if not p:
        return
    data: ig.InvoiceData = p["data"]
    st.markdown(f"**{data.customer_name}** · Invoice {data.invoice_number or '—'} · "
                f"{format_currency(ig.compute_totals(data)['total'], settings)}")
    st.caption("This invoice will be added to your recovery pipeline. If you set a "
               "reminder, it appears in your Daily Recovery Plan and — on the chosen "
               "date — in the Approval Queue to send a follow-up. Nothing is ever "
               "sent automatically.")
    want = st.toggle("Remind me to follow up on this invoice", value=True,
                     key="ig_single_rem_toggle")
    reminder_date = None
    if want:
        default = data.due_date or (today() + timedelta(days=7))
        if default < today():
            default = today()
        reminder_date = st.date_input("Remind me on", value=default,
                                      min_value=today(), key="ig_single_rem_date")
    c1, c2 = st.columns(2)
    if c1.button("Confirm & generate", type="primary", use_container_width=True):
        _finalize_single(mem, settings, reminder_date if want else None)
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        st.session_state.pop("ig_pending_single", None)
        st.rerun()


def _render_single_invoice() -> None:
    mem = get_memory()
    settings = get_settings()
    _seed_invoice_defaults(settings)

    # Reminder pop-up (opens after submit) + the outcome of the last generation.
    if st.session_state.get("ig_pending_single"):
        _single_reminder_dialog()
    _show_single_result(settings)

    if not ed.email_draft_available(settings):
        st.warning(
            "Email drafting isn't configured for this account. You can still generate "
            "and download the PDF, but no draft will be saved. Add credentials in "
            "**Settings → Email drafts**.",
            icon="✉️",
        )

    # --- Profile picker (outside the form so Load can rerun and pre-fill) ----
    profiles = mem.list_invoice_profiles()
    if profiles:
        ui.section("Reuse a saved customer format")
        labels = {p["customer_name"]: p for p in profiles}
        pc1, pc2 = st.columns([3, 1])
        chosen = pc1.selectbox("Customer profile", list(labels.keys()),
                               key="ig_profile_pick", label_visibility="collapsed")
        if pc2.button("📂 Load", use_container_width=True):
            _apply_invoice_profile(labels[chosen]["schema"])
            st.toast(f"Loaded format for {chosen}.", icon="📂")
            st.rerun()
        st.caption("Loading a format never sends anything and never touches invoices "
                   "you've already generated — it only pre-fills the form below.")

    with st.form("invoice_generator_form", clear_on_submit=False):
        ui.section("From")
        c1, c2 = st.columns(2)
        from_company = c1.text_input("Your company", key="ig_from_company")
        from_email = c2.text_input("Your email", key="ig_from_email")
        from_address = st.text_area("Your address (optional)", key="ig_from_address",
                                    height=70)

        ui.section("Bill to")
        c1, c2 = st.columns(2)
        customer_name = c1.text_input("Customer name", key="ig_customer_name")
        customer_email = c2.text_input("Customer email", key="ig_customer_email")
        customer_address = st.text_area("Customer address (optional)",
                                        key="ig_customer_address", height=70)

        ui.section("Invoice details")
        c1, c2, c3 = st.columns(3)
        invoice_number = c1.text_input("Invoice #", key="ig_invoice_number")
        issue_date = c2.date_input("Issue date", key="ig_issue_date")
        due_date = c3.date_input("Due date", key="ig_due_date")

        c1, c2 = st.columns([1, 3])
        currency_symbol = c1.text_input("Currency", key="ig_currency", max_chars=3)
        tax_rate = c2.number_input("Tax rate (%)", min_value=0.0, max_value=100.0,
                                   step=0.5, key="ig_tax_rate")

        ui.section("Line items")
        items_df = st.data_editor(
            st.session_state["ig_items_src"],
            num_rows="dynamic",
            use_container_width=True,
            key=f"ig_items_editor_v{st.session_state['ig_items_version']}",
            column_config={
                "Quantity": st.column_config.NumberColumn(min_value=0.0, step=1.0),
                "Unit price": st.column_config.NumberColumn(min_value=0.0, step=1.0,
                                                            format="%.2f"),
            },
        )

        ui.section("Email draft")
        c1, c2 = st.columns(2)
        email_subject = c1.text_input(
            "Subject",
            value=f"Invoice {invoice_number or ''} from {from_company or ''}".strip(),
        )
        email_body = c2.text_area(
            "Body",
            value=(
                f"Hi {customer_name or 'there'},\n\n"
                "Please find your invoice attached. Let me know if you have any "
                "questions.\n\n"
                f"{settings.message_signature or ''}"
            ).strip(),
            height=120,
        )
        notes = st.text_area("Notes on the invoice (optional)", key="ig_notes", height=70)

        save_profile = st.checkbox(
            "Save this customer's format as a profile (reusable from the dropdown)",
            value=True, key="ig_save_profile",
        )
        submitted = st.form_submit_button("Generate & save draft", type="primary",
                                          use_container_width=True)

    if not submitted:
        return

    # Keep the line-item source in sync with the user's edits before we read it.
    st.session_state["ig_items_src"] = items_df

    # Build the typed payload from the form values.
    line_items: list = []
    for _, row in items_df.iterrows():
        desc = str(row.get("Description") or "").strip()
        if not desc:
            continue
        try:
            qty = float(row.get("Quantity") or 0)
            price = float(row.get("Unit price") or 0)
        except (TypeError, ValueError):
            st.error("Quantity and unit price must be numeric.")
            return
        line_items.append(ig.LineItem(description=desc, quantity=qty, unit_price=price))

    data = ig.InvoiceData(
        from_company=from_company,
        from_email=from_email,
        from_address=from_address,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_address=customer_address,
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        currency_symbol=currency_symbol or "$",
        line_items=line_items,
        tax_rate_percent=float(tax_rate),
        notes=notes,
    )

    # Light pre-validation (the renderer re-checks) so the reminder pop-up only
    # opens for an invoice we can actually produce.
    if not from_company.strip():
        st.error("Your company name is required.")
        return
    if not customer_name.strip():
        st.error("Customer name is required.")
        return
    if not line_items:
        st.error("Add at least one line item.")
        return

    if save_profile:
        mem.upsert_customer(customer_name, customer_email)

    # Stash everything the finalize step needs, then open the reminder pop-up.
    st.session_state["ig_pending_single"] = {
        "data": data,
        "customer_email": customer_email,
        "email_subject": email_subject,
        "email_body": email_body,
        "save_profile": save_profile,
        "profile_schema": _collect_profile_schema() if save_profile else None,
    }
    st.session_state.pop("ig_result_single", None)
    st.rerun()


# Fields shown in the bulk mapping grid (order = display order). Driven by the
# dedicated bulk field set so the two never drift apart.
_BULK_FIELDS = list(cm.BULK_INVOICE_FIELDS.keys())
_BULK_LABELS = {
    "customer_name": "Customer name",
    "company_name": "Company name",
    "contact_person": "Contact person",
    "email": "Email",
    "mobile_number": "Mobile number",
    "address": "Address",
    "invoice_number": "Invoice #",
    "amount_due": "Amount",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "description": "Description",
}


def _render_bulk_invoices() -> None:
    mem = get_memory()
    settings = get_settings()

    st.caption("Upload a spreadsheet of outstanding invoices and generate a PDF for "
               "every row at once. Each customer's saved format (branding, currency, "
               "tax) is applied automatically, and any row whose invoice number you "
               "already created by hand is **skipped** — never overwritten.")

    uploaded = st.file_uploader("Invoice spreadsheet (CSV or Excel)",
                                type=["csv", "xlsx", "xls"], key="ig_bulk_file")
    if uploaded is None:
        st.info("No file yet. Each row needs at least a **customer name** and an "
                "**amount**; an invoice number and due date are recommended.")
        return

    try:
        df, meta = ingest.read_table(uploaded.getvalue(), uploaded.name)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the file: {exc}")
        return
    if df.empty:
        st.warning("No data rows found in that file.")
        return
    st.caption(f"{meta.get('rows', len(df))} rows · header on row "
               f"{meta.get('header_row', 0) + 1}")
    st.dataframe(df.head(10), use_container_width=True)

    # --- Column mapping (auto-detect via the bulk field set + overrides) -----
    ui.section("Map the columns")
    learned = mem.learned_aliases("invoice_bulk")
    base_mapping, _ = cm.detect_mapping(list(df.columns), "invoice_bulk", learned=learned)
    options = ["(none)"] + list(df.columns)
    mapping: dict = {}
    # Compact, best-fit grid: four selectboxes per row, a ✅ on auto-detected ones.
    cols_per_row = 4
    grid = st.columns(cols_per_row)
    for i, fld in enumerate(_BULK_FIELDS):
        default = base_mapping.get(fld, "(none)")
        idx = options.index(default) if default in options else 0
        label = ("✅ " if fld in base_mapping else "") + _BULK_LABELS.get(fld, fld)
        choice = grid[i % cols_per_row].selectbox(label, options, index=idx,
                                                  key=f"ig_bulk_map_{fld}")
        if choice != "(none)":
            mapping[fld] = choice

    if not ({"customer_name", "company_name"} & set(mapping)) or "amount_due" not in mapping:
        st.warning("Map an **Amount** plus at least one of **Customer name** or "
                   "**Company name** to continue.")
        return

    # --- Plan the batch (pure layer) ----------------------------------------
    rows = [{fld: row.get(col) for fld, col in mapping.items()}
            for _, row in df.iterrows()]
    results = bulk.plan_rows(
        rows,
        manual_exists=mem.manual_invoice_exists,
        get_profile=lambda name: (mem.get_invoice_profile_by_customer(name) or {}).get("schema"),
        default_issuer={"company": settings.company_name or "",
                        "email": settings.email_address or "", "address": ""},
        default_currency=settings.currency_symbol or "$",
    )
    counts = bulk.summarize(results)

    ui.section("Preview")
    status_icon = {bulk.READY: "✅ Ready", bulk.SKIPPED_MANUAL: "⏭️ Skip (manual)",
                   bulk.ERROR: "⚠️ Error"}
    preview = pd.DataFrame([{
        "Row": r.row_index + 1,
        "Customer": r.customer_name,
        "Invoice #": r.invoice_number,
        "Amount": r.amount,
        "Status": status_icon.get(r.status, r.status),
        "Detail": r.reason,
    } for r in results])
    st.dataframe(preview, use_container_width=True, height=320)

    mc = st.columns(3)
    mc[0].metric("Ready", counts[bulk.READY])
    mc[1].metric("Skipped (manual)", counts[bulk.SKIPPED_MANUAL])
    mc[2].metric("Errors", counts[bulk.ERROR])

    ready = [r for r in results if r.status == bulk.READY]
    if not ready:
        st.info("Nothing to generate yet — fix the errored rows or map more columns.")
        return

    teach = st.checkbox(
        "📚 Remember these column names so this client's files auto-map next time",
        value=True, key="ig_bulk_teach")
    save_drafts = False
    if ed.email_draft_available(settings):
        save_drafts = st.checkbox(
            "Also save an email draft for each row that has an email address",
            value=False, key="ig_bulk_drafts")

    if st.button(f"⚙️ Generate {len(ready)} invoice(s)", type="primary",
                 key="ig_bulk_go", use_container_width=True):
        # Stash the batch and open the reminder pop-up before generating.
        st.session_state["ig_bulk_pending"] = {
            "ready": ready, "mapping": mapping, "teach": teach,
            "save_drafts": save_drafts, "count": len(ready),
            "skipped": counts[bulk.SKIPPED_MANUAL],
        }
        st.session_state.pop("ig_bulk_zip", None)
        st.rerun()

    if st.session_state.get("ig_bulk_pending"):
        _bulk_reminder_dialog()

    if st.session_state.get("ig_bulk_zip"):
        st.success(st.session_state.get("ig_bulk_msg", "Invoices generated."))
        st.download_button("⬇️ Download all as ZIP", st.session_state["ig_bulk_zip"],
                           file_name="invoices.zip", mime="application/zip",
                           key="ig_bulk_dl", use_container_width=True)


def _finalize_bulk(mem, settings, days_after) -> None:
    """Generate the stashed batch after the reminder pop-up is answered. Each
    invoice is tracked into the recovery pipeline; when ``days_after`` is not
    ``None`` a per-invoice reminder (due date + days_after) is scheduled."""
    p = st.session_state.get("ig_bulk_pending")
    if not p:
        return
    ready, mapping = p["ready"], p["mapping"]
    if p["teach"]:
        mem.learn_aliases("invoice_bulk", mapping)  # Phase 4: detector learns

    rendered = bulk.render_all(ready)  # renders each PDF exactly once
    drafts_made = 0
    scheduled = 0
    for result, filename, pdf in rendered:
        mem.record_generated_invoice(
            customer_name=result.customer_name, invoice_number=result.invoice_number,
            amount=result.amount, currency=result.data.currency_symbol,
            source="auto", pdf_filename=filename,
        )
        reminder = (bulk.reminder_date_for(result.data, days_after)
                    if days_after is not None else None)
        _track_invoice(mem, settings, result.data, reminder)
        if reminder is not None:
            scheduled += 1
        if p["save_drafts"] and result.data.customer_email:
            ok, _reason = ed.save_draft_with_attachment(
                settings=settings, to_addr=result.data.customer_email,
                subject=f"Invoice {result.invoice_number} from "
                        f"{result.data.from_company}".strip(),
                body=(f"Hi {result.customer_name or 'there'},\n\n"
                      "Please find your invoice attached.\n\n"
                      f"{settings.message_signature or ''}").strip(),
                attachment_bytes=pdf, attachment_filename=filename,
                attachment_mime="application/pdf",
            )
            if ok:
                drafts_made += 1

    st.session_state["ig_bulk_zip"] = bulk.zip_pdfs(rendered)
    msg = f"Generated **{len(rendered)}** invoice(s)."
    if scheduled:
        msg += f" Scheduled **{scheduled}** reminder(s)."
    if p["skipped"]:
        msg += (f" Skipped **{p['skipped']}** matching invoices you created manually.")
    if p["save_drafts"]:
        msg += f" Saved **{drafts_made}** email draft(s)."
    st.session_state["ig_bulk_msg"] = msg
    st.session_state.pop("ig_bulk_pending", None)


@st.dialog("Schedule reminders for these invoices?")
def _bulk_reminder_dialog() -> None:
    mem, settings = get_memory(), get_settings()
    p = st.session_state.get("ig_bulk_pending")
    if not p:
        return
    st.markdown(f"**{p['count']}** invoice(s) ready to generate.")
    st.caption("These invoices will be added to your recovery pipeline. With reminders "
               "on, each one's reminder = its due date + the days below. When a "
               "reminder date arrives, that invoice appears in your Daily Recovery Plan "
               "and Approval Queue. Nothing is ever sent automatically.")
    want = st.toggle("Set follow-up reminders", value=True, key="ig_bulk_rem_toggle")
    days = 7
    if want:
        days = st.number_input("Remind this many days after each due date",
                               min_value=0, max_value=365, value=7, step=1,
                               key="ig_bulk_rem_days")
    c1, c2 = st.columns(2)
    if c1.button("Confirm & generate", type="primary", use_container_width=True):
        _finalize_bulk(mem, settings, int(days) if want else None)
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        st.session_state.pop("ig_bulk_pending", None)
        st.rerun()


# ---------------------------------------------------------------------------
# Navigation — grouped sidebar (Shopify/Linear style). One page per record
# type with internal tabs; no separate "Dashboard" + "Recovery" duplication.
# ---------------------------------------------------------------------------
SIDEBAR_GROUPS: list[tuple[str | None, list[tuple[str, callable]]]] = [
    (None, [
        ("✨ Get started", page_welcome),
        ("🏠 Home", page_dashboard),
        ("📤 Upload", page_upload),
    ]),
    ("Pipelines", [
        ("🧾 Invoices", page_invoices),
        ("📄 Quotes", page_quotes),
        ("🎯 Leads", page_leads),
    ]),
    ("Work", [
        ("🗂️ Daily Plan", page_daily_plan),
        ("✅ Approvals", page_approvals),
    ]),
    ("Insights", [
        ("👤 Customers", page_customer_history),
        ("📊 Reports", page_reports),
    ]),
    ("Setup", [
        ("🧩 Mapping", page_profiles),
        ("⚙️ Settings", page_settings),
    ]),
]
PAGES = {label: fn for _g, items in SIDEBAR_GROUPS for label, fn in items}


def _render_sidebar_nav(active: str) -> str:
    """Render the grouped sidebar nav with the active item styled as primary.

    Returns the (possibly new) active label after handling clicks.
    """
    for group_label, items in SIDEBAR_GROUPS:
        if group_label:
            st.sidebar.markdown(
                f"<div class='rrd-nav-group'>{group_label}</div>",
                unsafe_allow_html=True,
            )
        for label, _fn in items:
            is_active = (label == active)
            if st.sidebar.button(
                label, key=f"nav_{label}", use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["nav_choice"] = label
                st.rerun()
    return active


def main() -> None:
    user = _require_login()
    mem = get_memory()
    ui.inject_theme()
    settings = get_settings()

    if "_pending_nav" in st.session_state:
        st.session_state["nav_choice"] = st.session_state.pop("_pending_nav")
    # Brand-new signups land on the welcome page until they finish (or skip)
    # onboarding. The flag is persisted in their tenant DB so it survives
    # logouts. Once they've dismissed it, "🏠 Home" becomes the default.
    if not mem.onboarding_completed() and "nav_choice" not in st.session_state:
        st.session_state["nav_choice"] = "✨ Get started"
    choice = st.session_state.get("nav_choice", "🏠 Home")
    if choice not in PAGES:  # guard against legacy session state from old labels
        choice = "🏠 Home"
        st.session_state["nav_choice"] = choice

    # --- Top: workspace identity ---
    st.sidebar.markdown(
        "<div class='rrd-brand'><span class='dot'></span>Revenue Recovery Desk</div>",
        unsafe_allow_html=True,
    )
    workspace = user.company_name or user.email
    st.sidebar.markdown(
        f"<div class='rrd-side-workspace'>{workspace}</div>",
        unsafe_allow_html=True,
    )
    if crypto.using_dev_fallback_key():
        st.sidebar.warning("APP_SECRET_KEY not set — email credentials are not "
                           "securely encrypted.")

    # --- Middle: grouped navigation ---
    _render_sidebar_nav(choice)

    # --- Bottom: status + account actions ---
    s = analytics.stats(mem)
    st.sidebar.markdown("<div class='rrd-side-bottom'></div>", unsafe_allow_html=True)
    sb1, sb2 = st.sidebar.columns(2)
    sb1.metric("Pending", s["pending"])
    sb2.metric("Due today", s["due_today"])
    badge = "AI on" if ai_available(settings) else "AI off · rules"
    st.sidebar.caption(f"Mode: {badge}")
    if st.sidebar.button("Log out", key="nav_logout", use_container_width=True):
        for key in ("user", "settings", "scheduler"):
            st.session_state.pop(key, None)
        st.rerun()

    PAGES[choice]()


if __name__ == "__main__":
    main()
