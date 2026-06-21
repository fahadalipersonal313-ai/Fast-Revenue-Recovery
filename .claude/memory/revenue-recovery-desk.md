---
name: revenue-recovery-desk
description: "Separate Python/Streamlit product \"Revenue Recovery Desk\" built outside the CleanOps repo — full architecture, agents, safety model"
metadata: 
  node_type: memory
  type: project
  originSessionId: be97bd91-a845-4fc3-bbc1-e6dddc6277af
---

Built on **2026-06-14**, **Revenue Recovery Desk** is an agent-assisted Streamlit app for
freelancers/small businesses to recover money from overdue invoices, stale quotes, and
cold leads. **Agent-assisted but human-gated**: Python owns all money/date/priority/approval
logic; AI layer is optional and only polishes message wording. **The app never sends
messages** — it drafts, ranks, and queues them for human approval. It is a **different
product** from CleanOps AI ([[cleanops-commercial-goal]]).

**Location & path:** `D:\revenue-recovery-desk\` (confirmed actual location 2026-06-19;
earlier memory said `C:\Users\hp\Documents\revenue-recovery-desk\` — stale, project
actually on D: drive, likely moved due to C: drive space pressure). The CleanOps repo at
`C:\Users\hp\Documents\Project M` is separate (Next.js/Supabase data-cleaner).

**What is it:** Local single-user Streamlit app. **Per-tenant data isolation** as of
2026-06-19 SaaS conversion ([[rrd-saas-multi-tenant]]). No real sending in v1 — zero
WhatsApp/email/SMS integrations. The app only drafts, ranks, and queues messages for
human approval.

**Stack:** Streamlit + pandas + openpyxl + SQLite + APScheduler + Pydantic v2 + pytest.
Optional `anthropic` client for AI polish, fail-safe/off by default. Uses a `.venv` in
project root.

**Entry point:** `app.py` (consolidated to ~10 nav items in `SIDEBAR_GROUPS`, grouped sections):
- HOME: ✨ Get started (welcome), 🏠 Home (dashboard), 📤 Upload
- PIPELINES: 🧾 Invoices, 📄 Quotes, 🎯 Leads (each with internal tabs: Overview · Recommendations · Records · [Generate for invoices])
- WORK: 🗂️ Daily Plan, ✅ Approvals
- INSIGHTS: 👤 Customers, 📊 Reports
- SETUP: 🧩 Mapping, ⚙️ Settings

Welcome page auto-routes brand-new signups (persisted via `onboarding_completed_at` flag in tenant settings). Per-type Dashboard + Recovery pages were merged into single tabbed pages per type. Invoice Generator absorbed as a tab inside Invoices. `main()` is now guarded by `if __name__ == "__main__":` so imports from tests don't trigger the auth gate.

**⚠️ AGENTS.md is the authoritative, always-current changelog** — at `D:\revenue-recovery-desk\AGENTS.md`
([[rrd-sync-agents-md]]). Read it first each session for full detail on recent work;
this memory keeps only durable high-level facts.

## Core design philosophy (the "why")
- **Python owns ALL financial/date/priority/status/safety logic** — deterministic, testable.
- **AI is optional and fail-safe** (`src/ai_helper.py`): only rewrites message wording,
  never touches money, dates, priority, or approval. If `AI_ENABLED=true` but no API key,
  the app silently falls back to template mode — never crashes, never blocks.
- **Human approval is mandatory** for everything that matters: disputed invoices, final
  escalations, high-value contacts, any payment-status change. Supervisor agent
  (`src/supervisor_agent.py`) enforces this gating and never auto-approves those categories.
- **Agents/approval NEVER auto-send and NEVER flip payment status** (human-only).
- **Don't reintroduce gamification** (scores, badges, balloons, 3D candy buttons).

## Layout (file structure)
- **`app.py`** — Streamlit entry; all 10 pages + sidebar nav (`PAGES` dict, `main()`).
- **`src/ui.py`** — **design system** (theme CSS + render helpers, NO business logic).
  Pages call: `ui.page_header`, `ui.section`, `ui.kpi_cards`, `ui.empty_state`,
  `ui.checklist`, `ui.priority_chip`, `ui.welcome_styles()`, `ui.link_button()`,
  `ui.upgrade_card()`. Dark slate nav rail, **warm orange palette** (`#ea580c` primary,
  see [[rrd-brand-rules]]), flat buttons, hover-lift KPI cards, premium tabs with
  gradient underline, scroll fade-up animations, programmatic nav via `_goto()` +
  `st.session_state["_pending_nav"]`. Sidebar uses grouped section headers + custom
  button-based nav (NOT a single radio). Logout button moved to sidebar bottom.
- **`src/agents/`** — five agents + supporting modules:
  - `invoice_agent` — invoices logic
  - `quote_agent` — quotes logic
  - `lead_agent` — leads logic
  - `supervisor_agent` — safety rules + approval gating + Daily Recovery Plan builder
  - `communication_agent` — message generation; calls `ai_helper.py` for optional polish
  - `memory` — AgentMemory, duplicate prevention (dedupes per `(type, reference, customer)`
    triple), history
  - `auth` — users.db + per-tenant DBs under `data/tenants/<slug>/`
  - `crypto` — Fernet encryption
  - `column_mapper` — mapping + learned aliases
  - `ingest` — file read/detect
  - `approval_engine` — approval queue
  - `ai_helper` — AI polish
  - `scheduler` — APScheduler daily runs (in-process only)
  - `export_engine` — Excel exports
  - `config` — layered settings
- **`src/config.py`** — hard-coded defaults → env vars (`.env`, custom minimal loader,
  no python-dotenv) → user-edited Settings page (SQLite). Key settings:
  `high_value_threshold` (default $5000), `daily_analysis_time`, per-type cadences
  (invoice 5d / quote 4d / lead 3d), `ai_enabled`/`ai_model`/`ai_api_key` (read from env,
  never persisted).
- **`src/models.py`** — Pydantic contracts: `InvoiceDecision`, `QuoteDecision`,
  `LeadDecision`, `SupervisorDecision`, `GeneratedMessage`. Enums: `InvoiceStage`
  (Not due → Courtesy → Standard → Firm reminder → Missed promise follow-up → Final
  internal escalation → Payment plan discussion → Human review), `QuoteClass`
  (active/warm/cold/won/lost/review required), `LeadTemperature` (hot/warm/cold/dead),
  `RiskLevel`/`Priority` (none/low/medium/high/critical).
- **`src/message_templates.py`** — safe WhatsApp/email templates, no threatening/legal.
- **`data/users.db`** — accounts.
- **`data/tenants/<slug>/recovery_desk.db`** — per-tenant data.
- **`src/invoice_generator.py`** — pure: `InvoiceData`/`LineItem` → premium PDF bytes via
  `reportlab` (indigo accent, even-aligned, redesigned 2026-06-20); `compute_totals`,
  `suggest_filename`, `to_record` (→ canonical invoice record for the recovery pipeline).
- **`src/bulk_invoice.py`** — pure: bulk-generate from a spreadsheet; `plan_rows`
  (ready/skipped_manual/error), `render_all`+`zip_pdfs`, `reminder_date_for`.
- **`src/mailer.py`** — app-level SMTP (env `RRD_SMTP_*`) to SEND password-reset codes
  (separate from per-tenant IMAP draft-saving in `email_draft`).
- **`tests/`** — pytest; `test_app_smoke.py::test_all_pages_render_without_exception`
  renders every page. **148 tests passing** (2026-06-21).

## Running it
**In a normal terminal:**
```
.venv\Scripts\python.exe -m streamlit run app.py
```
Opens http://localhost:8501.

**In this bash harness** (shell can't exec `.exe` by path; pins bare `python` to system
`C:\Python314`, same interpreter .venv was built from — 3.14.6):
```
PYTHONPATH="D:\revenue-recovery-desk\.venv\Lib\site-packages" \
  python -m streamlit run app.py --server.headless=true --server.port=8501
```
- Health check: `http://localhost:8501/_stcore/health` → `ok`
- Tests: `PYTHONPATH="...\.venv\Lib\site-packages" python -m pytest -q`
- `.venv\Scripts\python.exe` / `run.bat` do NOT work in bash harness.

**Sample data:** `python sample_data\generate_samples.py` → Upload Center → "Load matching sample".

## Multi-tenant SaaS conversion (2026-06-19)
See [[rrd-saas-multi-tenant]]. Auth, encryption, per-tenant DB isolation, backward compat.

## Shipped since multi-tenant build (full detail in AGENTS.md)
- **Metrics layer** `src/analytics.py` (stats, aging buckets, status breakdown,
  recovery-rate-over-time) — done.
- **Invoice Generator** (4 phases): P1 manual form → premium PDF → Gmail draft;
  P2 per-customer saved profiles (reload dropdown); P3 bulk-from-file (auto-map,
  preview ready/skip/error, ZIP, skips manual invoices via `manual_invoice_exists`);
  P4 richer bulk fields (company/contact/mobile/address/description, `invoice_bulk`
  field set) + detector learns column names. Two tabs: Single / Bulk.
- **Invoice → recovery pipeline + reminders** (2026-06-21): generating an invoice
  (single or bulk) tracks it as an open invoice record (shows in Invoice Recovery +
  Daily Plan, no re-upload), with an optional `st.dialog` reminder pop-up BEFORE
  PDF/draft. Invoice agent honours `scheduled_reminder_date` → fires a reminder on
  that date → enters Daily Plan + Approval Queue; approving saves the draft. Single
  reminder = date picker (default due date); bulk = N days after each due date.
- **Account management** (2026-06-21): `auth.change_password`/`change_email`;
  pre-login password reset via 6-digit emailed code (`request_password_reset`/
  `reset_password`, hashed+30min expiry, single-use) using `src/mailer.py` SMTP.
  UI: login "Forgot password" tab + Settings "Account & security". Google/OIDC
  sign-in deferred (st.login available in Streamlit 1.58 if added later).

## Major additions since 2026-06-21 (live deployment day)
- **Now hosted/deployed**: Streamlit Cloud + Netlify landing — see [[rrd-deployment-live]].
- **Pricing & gating live**: Free (50 records/mo, 10 clients, no AI/bulk/reports) vs Pro
  ($15/mo unlimited). `src/gating.py` centralizes limits. `users.tier`/`pro_until` columns.
  See [[rrd-pricing-tiers-and-gating]].
- **Brand repaint**: indigo → warm orange palette. See [[rrd-brand-rules]].
- **Landing page**: separate static site at `landing/` (HTML/CSS), auto-deploys to Netlify.
- **Premium welcome page** for onboarding, auto-shown on first signup.
- **Duplicate dedupe improved**: `save_record` now matches on (customer+amount+due_date)
  when reference is missing/empty; `analyze_and_queue` clears recommendations per type
  before re-running to prevent doubling on re-upload.
- **Tenant email leak fixed**: `EMAIL_ADDRESS`/`EMAIL_APP_PASSWORD` env-var fallback removed
  from `config.py`; per-tenant encrypted store is the only source now.

## Known remaining limitations / next up
- **Ephemeral filesystem on Streamlit Cloud** — see [[rrd-streamlit-cloud-gotchas]]. Tenant
  data lost on every redeploy. Must migrate to Postgres (Neon/Supabase free tier) before
  first paying customer.
- **No automated billing yet** — Lemon Squeezy integration is Phase 3,
  see [[rrd-pricing-tiers-and-gating]]. Manual `auth.set_tier()` for now.
- **OAuth email** — Gmail + Outlook OAuth still on the roadmap, see [[rrd-email-oauth-integration-plan]].
- In-process scheduler (not a system service); only fires while app is running.
- AI key + SMTP config shared across tenants (app-level, intentional for now).
- No email verification yet (password reset now done).
