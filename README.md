# Revenue Recovery Desk

An **agent-assisted** Streamlit application that helps freelancers and small
businesses recover money from **overdue invoices**, **unanswered quotations**,
and **neglected sales leads**.

It reviews your records, decides which items need action, ranks them by
priority, drafts polite WhatsApp/email messages, asks for your approval, records
every decision, and schedules the next follow-up.

> **This is not an autonomous system.** Version 1 **never sends messages
> automatically.** It prepares actions and waits for your approval. Python owns
> all financial, date, priority, status and safety logic. The optional AI layer
> only interprets text and polishes wording — it never touches money, dates, or
> approval decisions.

---

## Key principles

- **Python does the maths and the rules** — overdue days, risk, recovery stage,
  priority scores, safety checks, approval gating.
- **AI is optional and fail-safe** — works fully without an API key. If AI is
  enabled but unavailable, it silently falls back to reliable templates.
- **A human approves everything** — disputed invoices, final escalations,
  high-value contacts and any payment-status change always require a person.

---

## Quick start (Windows)

```powershell
cd C:\Users\hp\Documents\revenue-recovery-desk

# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) create sample spreadsheets
python sample_data\generate_samples.py

# 4. Run the tests
pytest -q

# 5. Launch the app
streamlit run app.py
```

The app opens at <http://localhost:8501>.

> Tip: if you prefer not to activate the venv, prefix commands with the venv
> Python, e.g. `.venv\Scripts\python.exe -m streamlit run app.py`.

---

## Testing the sample files

1. Run `python sample_data\generate_samples.py` to create
   `sample_invoices.xlsx`, `sample_quotes.xlsx`, `sample_leads.xlsx`.
2. Start the app and open **Upload Center**.
3. Pick a record type, click **Load matching sample** (or upload your own file).
4. Review the auto-detected **column mapping**, adjust if needed, then click
   **Process and analyze**.
5. Check **Daily Recovery Plan**, **Approval Queue**, and the per-type pages.

The sample files deliberately include paid/overdue/disputed invoices, missed
promises, high-value items, won/lost quotes, price objections, hot/cold leads,
messy phones/emails, missing dates, varied status names, and duplicate names.

---

## Enabling optional AI mode

AI is **off by default**. To enable it:

1. Copy `.env.example` to `.env`.
2. Set:
   ```
   AI_ENABLED=true
   AI_API_KEY=your-key-here
   AI_MODEL=claude-opus-4-8
   ```
3. Install the optional client (already in requirements): `pip install anthropic`.
4. Restart the app. The sidebar shows **🟢 AI on** when active.

If `AI_ENABLED=true` but no key is present, the app stays in reliable rules mode
and the Settings page warns you — it never crashes and never blocks recovery.

The API key is read **only** from the environment and is never written to the
database.

---

## Project structure

```
revenue-recovery-desk/
├─ app.py                 # Streamlit entry point (all 10 pages)
├─ requirements.txt
├─ README.md
├─ .env.example
├─ src/
│  ├─ config.py           # settings (env + persisted)
│  ├─ models.py           # Pydantic decision models
│  ├─ utils.py            # date/money/phone/email/status helpers
│  ├─ database.py         # SQLite schema + access
│  ├─ memory.py           # agent memory, duplicate prevention, history
│  ├─ column_mapper.py    # header detection + manual mapping
│  ├─ invoice_agent.py    # invoice recovery logic
│  ├─ quote_agent.py      # quote recovery logic
│  ├─ lead_agent.py       # lead scoring + recovery logic
│  ├─ message_templates.py# safe WhatsApp/email templates
│  ├─ communication_agent.py # message generation (+ optional AI polish)
│  ├─ supervisor_agent.py # safety rules + approval gating + daily plan
│  ├─ approval_engine.py  # approval queue + analysis orchestration
│  ├─ scheduler.py        # APScheduler daily run
│  ├─ export_engine.py    # Excel exports
│  └─ ai_helper.py        # optional, fail-safe AI layer
├─ sample_data/           # sample generator + generated files
├─ data/                  # SQLite database (created at runtime)
├─ exports/               # generated Excel files
└─ tests/                 # pytest suite
```

## Pages

Dashboard · Upload Center · Daily Recovery Plan · Invoice Recovery ·
Quote Recovery · Lead Recovery · Approval Queue · Customer History ·
Saved Reports · Settings.

---

## Safety guarantees (v1)

The supervisor agent **never auto-approves**: automatic final escalation, legal
threats, invoice write-offs, disputed-invoice actions, high-value sensitive
communications, or payment-status changes. Messages contain no threats or legal
language. Approving an item records intent and schedules a task — it does **not**
transmit anything.

---

## Known limitations

- **No real sending.** By design, v1 prepares messages only; there is no
  WhatsApp/email/SMS integration.
- **Single-user, local.** SQLite stored under `data/`; no multi-user auth.
- **Scheduler runs in-process.** The APScheduler job only fires while the app is
  running; it is not a system service.
- **Duplicate detection is per (type, reference, customer).** Records that share
  these collapse to one (e.g. two leads with the same source + name).
- **AI polish is best-effort.** When enabled it rewrites wording only; output is
  not guaranteed identical between runs.

## Recommended version 2 features

- Approved-channel sending (WhatsApp Business API, email) with audit trail.
- Multi-user accounts and role-based approval.
- Configurable message template editor in the UI.
- Per-customer communication preferences and quiet hours.
- Richer analytics (recovery rate over time, aging buckets, cohort views).
- Webhook/CRM sync and a persistent system scheduler service.
