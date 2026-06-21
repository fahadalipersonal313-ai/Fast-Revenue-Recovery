---
name: rrd-ai-and-email-integration
description: "Revenue Recovery Desk — AI (Gemini free tier) + email-draft integration, and the Avast TLS gotcha"
metadata: 
  node_type: memory
  type: project
  originSessionId: c5c6b5d0-1955-4685-b686-fd29ef976327
---

Built 2026-06-19 on **Revenue Recovery Desk** ([[revenue-recovery-desk]], at
`D:\revenue-recovery-desk\`): optional email drafting + a multi-provider AI layer.

**Email drafting:** approving an invoice/quote/lead saves a DRAFT (never sends)
to the user's own Drafts folder via IMAP `APPEND`. Code in `src/email_draft.py`
(fail-safe like the AI helper — any error returns `(False, reason)`, never
crashes the approval flow). Config is env-only (never persisted):
`EMAIL_DRAFT_ENABLED`, `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` (Gmail App Password,
needs 2FA), `EMAIL_IMAP_HOST/PORT`, `EMAIL_DRAFTS_FOLDER` (default `[Gmail]/Drafts`).
Invoice/quote spreadsheets now support an `email` column (auto-detected in
`column_mapper.py`); the Approval Queue also has a manual "Customer email" box
that `upsert_customer`s the address. `memory.get_customer_email()` looks it up.
Drafts only save when the customer has an email on file.

**AI layer (provider-agnostic):** `src/ai_helper.py` exposes `improve_message`
and `summarize_context`, dispatching on `settings.ai_provider` — "gemini"
(default, free tier) or "anthropic" (paid). Keys are env-only:
`GEMINI_API_KEY` / `ANTHROPIC_API_KEY` (or `AI_API_KEY` for either). The user
runs the **Gemini free tier**. Uses the **`google-genai`** SDK (NOT the
deprecated `google-generativeai`).

**Three gotchas solved (don't re-diagnose these):**
1. **Avast breaks HTTPS.** Avast "Web/Mail Shield" intercepts TLS and re-signs
   with its own root cert → Python fails `CERTIFICATE_VERIFY_FAILED`. certifi's
   bundle does NOT fix it. Fix: `truststore` (in requirements), injected at app
   startup via `src/net_bootstrap.enable_os_trust_store()` (called first thing
   in `app.py`), which routes verification through the Windows trust store where
   Avast's cert lives. This also fixes the email IMAP TLS. Never disable AV or
   skip verification.
2. **Model quota.** `gemini-2.0-flash` returns 429 RESOURCE_EXHAUSTED on the
   user's account. **Default model is `gemini-2.5-flash`** (works on their free
   tier). Set in `config.Settings.ai_model_resolved`.
3. **2.5-flash truncation.** 2.5 models "think" by default and reasoning tokens
   count against `max_output_tokens`, truncating short messages. Fix: pass
   `ThinkingConfig(thinking_budget=0)` for Gemini calls (done in `ai_helper`).

**More AI features added later 2026-06-19:** (1) **Tone variants** —
`ai_helper.message_tone_variants` returns gentle/neutral/firm rewrites as JSON;
UI shows them in tabs in the Approval Queue with "Use this version". (2)
**Reply-intent detection** — `ai_helper.classify_reply` reads a pasted customer
reply and returns `{intent, confidence, promised_date, summary}` as JSON;
intent is one of REPLY_INTENTS. The deterministic next-step mapping lives in
`src/reply_actions.py` (`suggest_next_step`/`describe_classification`) — **AI
reads, Python decides** (dispute/already_paid force needs_human). UI is a
popover "📩 Customer replied? Analyze it". JSON parsed via `_extract_json`
(handles ```json fences). Classifier prompt is fed today's date so relative
dates ("next Friday") resolve. Tests in `tests/test_ai_features.py` (58 total
passing).

**Gotcha #4 — stale persisted ai_model broke ALL AI silently.** Persisted DB
settings OVERRIDE `.env`. An old "Save settings" had stored
`ai_model="claude-opus-4-8"` in the settings table; after switching provider to
gemini, the app sent that Claude model name to the Gemini API → rejected →
fail-safe fell back to templates with no error. CLI tests passed because they
used fresh `Settings()` (no DB). Fix: `config.ai_model_resolved` now ignores a
model id that doesn't match the active provider (claude-* under gemini, or
gemini-* under anthropic) and uses the provider default. If AI silently does
nothing in the app but works in a CLI script, **suspect persisted DB settings**
(`SELECT * FROM settings` in `data/recovery_desk.db`), not the code.

**Rate limits / quota (IMPORTANT):** Gemini free tier has BOTH a per-minute
throttle AND a small **per-day** cap. `gemini-2.5-flash` free tier allows only
**~20 requests/day** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
limit 20) — we exhausted it during a single day of building/testing, which made
features "stop working" with the generic fail-safe warning. **Default model is
therefore `gemini-2.5-flash-lite`** (set in `config.ai_model_resolved`), which
has a much larger free-tier daily quota and gives equally good rewrites. A 429
is swallowed by the fail-safe → empty result → template fallback (never a
crash). If features silently stop after working: check for a 429
RESOURCE_EXHAUSTED (daily quota) before assuming a code bug — the error is
hidden inside the try/except, so reproduce the raw `client.models.generate_content`
call to see it. `gemini-2.0-flash` and `gemini-2.0-flash-lite` were already
quota-exhausted/unavailable on this account.

**Streamlit widget-state gotcha:** cannot assign `st.session_state[widget_key]`
AFTER the widget is instantiated in the same run (raises StreamlitAPIException).
The "Use tone version" button stashes the chosen text in `apply_msg_<id>` and
reruns; the actual write to `msg_<id>` happens at the TOP of the next run,
before the `st.text_area` is created. Same pattern needed for any
programmatic widget update.

**Safety model unchanged:** AI only polishes wording / reads text. All money,
dates, priority, risk, and approval decisions stay in Python. Email only ever
drafts, never sends. This human-in-control story is a deliberate selling point.

**Run/test:** `.venv\Scripts\python.exe -m streamlit run app.py` (port 8501);
`pytest -q` → 73 passing after the multi-tenant build ([[rrd-saas-multi-tenant]]). Restarting Streamlit on Windows:
kill via `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where ...
CommandLine -like '*streamlit*' | Stop-Process`.
