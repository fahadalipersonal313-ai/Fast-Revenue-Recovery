# AGENTS.md — Revenue Recovery Desk (project memory)

Durable context for AI/dev sessions. Keep this updated as the source of truth.

## What this is
Local, single-user **Streamlit** app that helps freelancers/small businesses recover
money from overdue invoices, stale quotes, and cold leads. **Agent-assisted but
human-gated**: Python owns all money/date/priority/approval logic; an optional AI
layer only polishes message wording. **The app never sends messages** — it drafts,
ranks, and queues them for human approval. Per-tenant data isolation.

## Run it (Windows + this bash harness)
This shell **cannot execute a `.exe` by path** and pins bare `python` to system
`C:\Python314`. The venv (`.venv`) was built from that same interpreter
(`pyvenv.cfg`: 3.14.6). So run system Python against the venv's packages:

```
PYTHONPATH="D:\revenue-recovery-desk\.venv\Lib\site-packages" \
  python -m streamlit run app.py --server.headless=true --server.port=8501
```
- Health check: `http://localhost:8501/_stcore/health` → `ok`.
- Tests: `PYTHONPATH="...\.venv\Lib\site-packages" python -m pytest -q` (148 passing).
- `run.bat` / direct `.venv\Scripts\python.exe` do NOT work in this shell (they work
  in a normal terminal).

## Layout
- `app.py` — Streamlit entry; all pages + sidebar nav (`PAGES` dict, `main()`).
- `src/ui.py` — **design system** (theme CSS + render helpers). No business logic.
- `src/analytics.py` — **metrics layer** (pure read functions): `stats(mem)`,
  `aging_buckets(mem)`, `status_breakdown(mem, record_type)`,
  `recovery_rate_over_time(mem, period=..., periods=...)`. No SQL in pages.
- `src/` agents: `invoice_agent`, `quote_agent`, `lead_agent`, `supervisor_agent`,
  `communication_agent`; plus `memory` (AgentMemory), `auth` (users.db + per-tenant
  DBs under `data/tenants/<slug>/`), `crypto`, `column_mapper` (mapping + learned
  aliases), `ingest` (file read/detect), `approval_engine`, `ai_helper`,
  `scheduler`, `export_engine`, `email_draft` (IMAP draft-save, no SMTP — has
  `save_draft` + `save_draft_with_attachment`), `invoice_generator` (pure:
  `InvoiceData` → PDF bytes via `reportlab`), `bulk_invoice` (pure: mapped rows
  → planned `BulkResult`s with status `ready`/`skipped_manual`/`error`, then
  `render_all` + `zip_pdfs`; injects `manual_exists`/`get_profile` callbacks),
  `config`.
- Invoice Generator persistence: `invoice_profiles` table (one saved invoice
  *format* per customer, keyed by normalised name) and `generated_invoices`
  ledger (`source='manual'|'auto'`, UNIQUE on `(customer_key, invoice_number)`).
  Memory methods: `save_invoice_profile`, `list_invoice_profiles`,
  `get_invoice_profile_by_customer`, `delete_invoice_profile`,
  `record_generated_invoice`, `manual_invoice_exists`.
- `data/users.db` — accounts. `data/tenants/<slug>/recovery_desk.db` — per-tenant data.
- `tests/` — pytest; `test_app_smoke.py::test_all_pages_render_without_exception`
  renders every page; `test_analytics.py` covers the metrics layer.

## Conventions / invariants
- Presentation lives in `src/ui.py`; pages call `ui.page_header`, `ui.section`,
  `ui.kpi_cards`, `ui.empty_state`, `ui.checklist`, `ui.priority_chip`. SQL/metrics
  go through `src/analytics.py` — never inline `db.query` in a page.
- Agents/approval NEVER auto-send and NEVER flip payment status (human-only).
- AI is fail-safe: works fully without a key; falls back to templates.
- Don't reintroduce gamification (scores, badges, balloons, 3D candy buttons).

## Recent work (2026-06)
- **Document generation overhaul** (2026-06-22): five linked upgrades to invoice/
  quote generation.
  - **Premium PDF restyle**: `render_invoice_pdf` switched from the old indigo
    accent (a brand-rule violation) to a neutral charcoal palette
    (`#111827`/`#374151`/`#6b7280`) — deliberately colour-agnostic so it reads as
    "top-tier corporate".
  - **Logo + e-signature** (superseded an earlier letterhead-banner/full-page
    design — letterhead quality varies too much across users — clarity, blur,
    watermarks — to place reliably, so it was replaced with a logo, which is more
    standardized): `InvoiceData`/`QuoteData` have optional `logo_png` +
    `logo_position` (`"top_left"`/`"top_center"`/`"top_right"`, drawn as a small
    fixed-size mark via `Image.hAlign`), `signature_png` (bottom-right where the
    content ends) + `signature_label`. `from_company` is mandatory; `from_email`/
    `from_address`/`from_phone` are optional. Helper `_scaled_image()` fits images
    to a box preserving aspect ratio and returns `None` for unreadable bytes, so a
    bad upload never sinks the PDF. UI: `_render_branding_inputs(prefix, kind)`
    adds the logo (+ position selector) and signature uploaders to the invoice/
    quote single + bulk generators; bytes live in
    `st.session_state["{prefix}_logo_bytes"]` / `{prefix}_logo_position` etc. so
    they survive the reminder-dialog rerun.
  - **Quote generator (NEW)**: `src/quote_generator.py` (`QuoteData`,
    `render_quote_pdf`, `to_record` → quote record, reuses invoice `LineItem`/
    `CustomField`/`_money`/`_scaled_image`) + `src/bulk_quote.py` mirroring
    `bulk_invoice.py`. Wired into a new "🧮 Generate" tab on the Quotes page
    (`_render_single_quote` / `_render_bulk_quotes`). Generated quotes optionally
    enter the normal quote-recovery pipeline via `analyze_and_queue`.
  - **Standardized templates**: `src/templates.py` builds downloadable `.xlsx`
    templates whose headers map 1:1 onto `BULK_INVOICE_FIELDS` / new
    `BULK_QUOTE_FIELDS` (so an unedited template auto-detects every column — tested).
    Download buttons via `_render_template_download(kind)`.
  - **Custom "+" fields + AI analysis**: `_render_custom_field_editor` is a
    dynamic-row data_editor (the "+" adds rows); values become `CustomField`s shown
    in an "Additional details" grid on the PDF. When AI is on,
    `ai_helper.analyze_custom_fields` lightly cleans label casing/spacing — with a
    hard guard that **rejects the whole response if a value's digits change**, so a
    PO/VAT number can never be silently mangled. Fails safe to raw text otherwise.
  - **Guided tour step 4**: added a Settings stop explaining how to connect email
    so approved follow-ups save to the Gmail/IMAP Drafts folder.
  - 16 new tests in `tests/test_quote_and_templates.py`; full suite 164 passing.
- **Letterhead → logo replacement** (2026-06-22/23): dropped the full-page
  letterhead detection subsystem entirely (letterhead quality varies too much
  across users — blur/watermarks/resolution — to auto-detect a blank area
  reliably). Replaced with a small fixed-size **logo** + `logo_position`
  (`top_left`/`top_center`/`top_right`) on `InvoiceData`/`QuoteData`.
  `from_company` is mandatory again; `from_address`/`from_email`/`from_phone`
  (new field) stay optional. Both generators are back to plain
  `SimpleDocTemplate` (no `BaseDocTemplate`/`Frame`/`PageTemplate`). UI session
  keys renamed `{prefix}_letterhead_bytes` → `{prefix}_logo_bytes` +
  `{prefix}_logo_position`. Full suite 174 passing.
  - **Deploy gotcha**: after pushing this kind of dataclass-field rename, a
    `TypeError` on `ig.InvoiceData(...)`/`qg.QuoteData(...)` construction in
    the deployed Streamlit Cloud app (but not locally) means the running
    process has a **stale cached `invoice_generator`/`quote_generator`
    module** from before the rename — `app.py`'s source reloads but the
    already-imported module doesn't. Fix: Streamlit Cloud → **Manage app** →
    **⋮ → Clear cache**, then **⋮ → Reboot app** (a plain rerun isn't enough,
    it needs a process restart).
- **GLM (Z.ai) added as 3rd AI provider** (2026-06-30): alongside `gemini`
  (default) and `anthropic`. GLM's `glm-4.5-flash`/`glm-4.7-flash` are free
  (rate-limited). The endpoint is OpenAI-compatible, so `_glm_complete` in
  `ai_helper.py` calls `{GLM_BASE_URL}/chat/completions` over `requests` (no new
  SDK; default base `https://api.z.ai/api/paas/v4`, override via `GLM_BASE_URL`
  for the China endpoint). Key read from `GLM_API_KEY` (or `AI_API_KEY`); never
  persisted. `config.ai_model_resolved` now maps 3 providers and ignores a model
  id belonging to another provider (default `glm-4.5-flash`). Fully fail-safe
  (no key / non-200 / network error / junk payload → `None` → templates). 9 new
  tests in `tests/test_glm_provider.py`; suite 183 passing.
- Fixed logout button visibility (moved to top of sidebar, full-width).
- **UI redesign → premium SaaS look** (`src/ui.py` rewritten, `app.py` restyled):
  dark slate nav rail, single indigo accent (`#4f46e5`), flat buttons, clean KPI
  cards, premium login + empty states, de-gamified dashboard, programmatic nav via
  `_goto()` + `st.session_state["_pending_nav"]` / radio `key="nav_choice"`.
  Streamlit primary buttons need selectors for BOTH `kind="primary"` and
  `kind="primaryFormSubmit"`.
- **Phase 1 — metrics layer extracted** to `src/analytics.py`:
  - Ported `_stats()` out of `app.py` as `analytics.stats(mem)`; dropped the unused
    gamification `score` field (40/35/25 weighted) and its `rec_ratio`/`comp_ratio`/
    `ontime_ratio` helpers. Public dict shape otherwise unchanged.
  - Added `aging_buckets(mem, on_date=...)` — unpaid invoices grouped into
    Not yet due / 1–30 / 31–60 / 61–90 / 90+ days; always returns every bucket so
    charts get a stable x-axis. Uses `payload_json.due_date`; skips invoices with
    no parseable due date.
  - Added `status_breakdown(mem, record_type)` — count + amount per canonical
    status, sorted by amount desc; empty status collapses to `unknown`.
  - Added `recovery_rate_over_time(mem, period="month"|"week", periods=N,
    on_date=...)` — invoice cohorts bucketed by `records.created_at` via SQLite
    `strftime`; returns exactly `periods` entries, oldest first, zero-filled.
  - All three call sites in `app.py` (dashboard, approval queue caption, sidebar
    pending metric) updated; local `_stats` removed; cleaned now-unused imports
    (`queue_counts`, `parse_date`, `datetime.date`).
  - 22 unit tests in `tests/test_analytics.py`; full suite 95 passing.
- **Invoice Generator — Phase 1** (2026-06-20): new "🧮 Invoice Generator" page
  between Daily Recovery Plan and Invoice Recovery. Manual form (data_editor for
  line items) → renders PDF via `reportlab` (new dep) → saves Gmail draft with
  PDF attached, or just offers download if email drafting isn't configured. New
  module `src/invoice_generator.py` (pure: `InvoiceData` + `LineItem` dataclasses,
  `render_invoice_pdf()`, `compute_totals()`, `suggest_filename()`, fully
  unit-tested). New `email_draft.save_draft_with_attachment()` extension; original
  `save_draft` untouched. 10 new tests; smoke test covers the new page.
- **Invoice Generator — Phase 2** (2026-06-20): per-customer **invoice profiles**.
  On "Generate & save draft" (checkbox on by default) the form's reusable fields
  (issuer, customer, currency, tax, line items, notes — *not* invoice #/dates)
  are saved as a profile keyed by customer; every produced invoice is logged in
  `generated_invoices` as `source='manual'`. A dropdown at the top of the page
  reloads any saved customer format to pre-fill the form. Form is driven by
  `st.session_state` keys (`ig_*`); the line-item `data_editor` uses a **versioned
  key** (`ig_items_editor_v{n}`) bumped on profile load so the table actually
  resets (can't seed a keyed data_editor directly — known Streamlit gotcha).
  `manual_invoice_exists()` is the guard Phase 3 will honour. 9 new tests in
  `tests/test_invoice_profiles.py`.
- **Invoice Generator — Phase 3** (2026-06-20): **bulk generation from a file**.
  The page is now two tabs — *Single invoice* (Phase 1/2) and *Bulk from file*.
  Bulk flow: upload CSV/Excel → `ingest.read_table` → `cm.detect_mapping` (invoice
  field set) with manual override selectboxes → `bulk.plan_rows` classifies each
  row `ready`/`skipped_manual`/`error` → preview table + Ready/Skipped/Errors
  metrics → "Generate N" renders each PDF once (`bulk.render_all`), logs each as
  `source='auto'`, optionally saves an email draft per row with an email, and
  offers a ZIP (`bulk.zip_pdfs`). Per-row **amount** becomes a single line item;
  the customer's saved profile only supplies branding/currency/tax/address/notes
  (never the amount). Manual invoices with a matching `(customer, number)` are
  skipped, never overwritten. ZIP bytes are stashed in `st.session_state` so the
  download button survives reruns. 10 new tests in `tests/test_bulk_invoice.py`.
- **Invoice Generator — Phase 4** (2026-06-20): richer bulk fields + the
  detector **learns**. New dedicated field set `cm.BULK_INVOICE_FIELDS` (record
  type `"invoice_bulk"`, its own learned-alias pool so it never reshapes Upload
  Center's `"invoice"` mapping) adds `company_name`, `contact_person`,
  `mobile_number`, `address`, `description` on top of customer/number/amount/
  dates/email. `bulk.build_invoice_data` composes the bill-to block: heading =
  customer_name → company → contact; the others become address lines
  (`Attn: …`, address, `Mobile: …`). Identity/dedup label falls back to company
  name when no customer name. Bulk mapping grid is now a compact 4-per-row layout
  with a ✅ on auto-detected columns and friendly labels (`_BULK_LABELS`); a
  "📚 Remember these column names" checkbox calls `mem.learn_aliases("invoice_bulk",
  mapping)` on generate so a client's files auto-map next time. Required: an
  Amount plus at least one of Customer/Company name. 4 new tests; full suite
  **128 passing**.
- **Account management — profile + password reset** (2026-06-21): `auth.py`
  gained `change_password`, `change_email` (verify current password; email change
  keeps the tenant slug/data, enforces uniqueness), and a pre-login reset flow
  `request_password_reset` (stores a hashed 6-digit code + 30-min expiry, returns
  the code or None without leaking which emails exist) / `reset_password`
  (single-use, expiring). Schema upgraded in place via idempotent `_migrate`
  (adds `reset_code_hash`, `reset_expires_at`). New `src/mailer.py` sends the
  code via **app-level SMTP** read from `RRD_SMTP_*` env vars (separate from the
  per-tenant IMAP draft creds, since reset runs before login); degrades cleanly
  when unconfigured. UI: a "Forgot password" tab on the login page (only active
  when SMTP is configured) and an "Account & security" expander in Settings.
  Google/OIDC sign-in intentionally deferred (`st.login` is available in
  Streamlit 1.58 + Authlib if added later). 11 new tests in
  `tests/test_auth_account.py`; suite **148 passing**.
- **Invoice → recovery pipeline + reminders** (2026-06-21): generating an
  invoice (single *or* bulk) now feeds the whole recovery loop, so the same
  invoices never need re-uploading. Flow: click Generate → an `st.dialog`
  reminder pop-up opens **before** PDF/draft → on confirm the invoice is tracked
  and the PDF/draft are produced. Pieces:
  - `ig.to_record(data, scheduled_reminder_date=...)` — pure projection of
    `InvoiceData` into the canonical invoice-record dict (amount = total).
  - `app._track_invoice` calls `analyze_and_queue(mem, settings, {"invoice":[rec]})`
    → persists an **open** record (shows in Invoice Recovery + Daily Recovery
    Plan) and enqueues an approval iff a reminder/chase is due.
  - `invoice_agent` honours `scheduled_reminder_date`: when reached (and unpaid)
    it raises a COURTESY reminder even before the due date (`reminder_due`,
    +20 score) so it surfaces in the plan and Approval Queue; approving there
    saves the reminder draft (existing `approve()` path). Nothing auto-sends.
  - Reminder dates: single invoice = a date picker defaulting to the due date
    (fallback today+7); bulk = "N days after each invoice's due date" via
    `bulk.reminder_date_for(data, days)` (fallback issue date → today).
  - Dialog plumbing uses `st.session_state` (`ig_pending_single`/`ig_bulk_pending`,
    `ig_result_single`/`ig_bulk_zip`) so downloads/results survive the rerun the
    dialog triggers. 9 new tests in `tests/test_reminder_pipeline.py`; suite
    **137 passing**.
- **Invoice PDF redesign** (2026-06-20): `render_invoice_pdf` rebuilt for a
  premium, consistent look — indigo (`#4f46e5`) accent title + total bar, bold
  Helvetica type scale, even left/right edges (issuer + meta header table,
  full-width zebra line-item table, right-aligned totals all share the 7.1"
  content width), `HRFlowable` accent/hairline rules, and a centered footer.
  Issuer name is `settings.company_name` (defaults to the placeholder
  "Your Company" from `config.py` until the user sets it in Settings).

- **Fix: stray DeltaGenerator help text on Customers + Reports** (2026-06-22):
  `page_customer_history` (line ~1045) and `page_reports` (line ~1078) used a
  ternary *expression-statement* — `st.dataframe(...) if rows else st.caption(...)`
  — to choose between rendering a table and an empty-state caption. Because
  `st.dataframe` always executes and returns a `DeltaGenerator`, and the ternary
  result was discarded rather than rendered, Streamlit was dumping the
  `DeltaGenerator` repr/help text into the page body. Fixed by replacing both
  with proper `if rows: ... else: ...` blocks. If a future page shows similar
  raw object text instead of a widget, check for an `st.<widget>(...) if cond
  else st.<other>(...)` expression-statement pattern.

## Open roadmap (proposed) — recommended order
1. ~~Metrics layer~~ — **done** (Phase 1, see above).
2. **Module dashboards + mega dashboard**: turn per-type pages into real module
   dashboards (KPIs + aging/status charts + filtered queue + outcomes); main
   Dashboard becomes aggregate rollup with drill-down buttons. Charts call the
   new `analytics.aging_buckets` / `status_breakdown` / `recovery_rate_over_time`.
3. **Smart Upload wizard**: build on existing `column_mapper` profiles/learned
   aliases — "new client setup" with manual header entry (no file needed),
   recognition panel (recognized vs missing vs unmapped), keeps learning.
4. Premium polish: empty states everywhere, onboarding wizard, charts.

### Invoice Generator roadmap
- **Phase 1 (done)**: manual form → PDF → Gmail draft.
- **Phase 2 (done)**: per-customer invoice profiles; dropdown reload;
  `generated_invoices` ledger with `source='manual'`.
- **Phase 3 (done)**: bulk generate from an uploaded file in the "Bulk from
  file" tab; per-customer profiles applied automatically; rows matching a manual
  `(customer, invoice_number)` are skipped and the skipped count is reported.
- **Phase 4 (done)**: richer bulk fields (company/contact/mobile/address/
  description) via the dedicated `invoice_bulk` field set, compact 4-col mapping
  grid, and a "Remember these column names" toggle that teaches the
  `invoice_bulk` learned-alias pool so a client's files auto-map next time.

### Invoice Generator roadmap
- **Phase 1 (done)**: manual form → PDF → Gmail draft.
- **Phase 2 (pending)**: save customer + field schema as an *invoice profile*
  on Done; dropdown loads profile to pre-fill the form. Tables:
  `invoice_profiles` and `generated_invoices` (`source='manual'|'auto'`).
- **Phase 3 (pending)**: bulk auto-generate from Upload Center when
  `column_mapper` matches rows to a saved profile. Auto-gen **must skip** any
  `(customer, invoice_number)` that already has a `source='manual'` row, and
  report skipped count.
- **Phase 4 (pending)**: saved profile field schema feeds `column_mapper`
  learned aliases for that customer.
