---
name: rrd-saas-multi-tenant
description: "Revenue Recovery Desk — multi-tenant auth, per-tenant data isolation, encrypted credentials (SaaS conversion)"
metadata: 
  node_type: memory
  type: project
  originSessionId: c5c6b5d0-1955-4685-b686-fd29ef976327
---

Built 2026-06-19/20 on **Revenue Recovery Desk** ([[revenue-recovery-desk]],
[[rrd-ai-and-email-integration]]) to convert it from single-user/local into a
sellable multi-tenant **SaaS**. The user confirmed they want the hosted SaaS
model (over iOS/Play store) and to onboard pilot clients.

**Auth & isolation (`src/auth.py`):** email/password signup+login. Passwords
hashed with **PBKDF2-HMAC-SHA256, 200k iterations, unique per-user salt** (stdlib
`hashlib`, no extra dep). Users live in `data/users.db`. Each signup gets a
tenant slug and its OWN SQLite file at `data/tenants/<slug>/recovery_desk.db` —
true data isolation (verified: two tenants get different DB paths, nothing
shared). Key fns: `signup()`, `login()`, `tenant_db_path()`, `find_user_by_id()`.

**Encrypted per-tenant credentials (`src/crypto.py`):** Fernet symmetric
encryption; key derived via SHA-256 from `APP_SECRET_KEY` env var (the operator
holds it). Each client enters THEIR OWN email + Gmail app password in the
Settings page → encrypted before disk, stored in their tenant DB. `encrypt()`,
`decrypt()` (garbage → None), `using_dev_fallback_key()`. If `APP_SECRET_KEY`
unset, falls back to an insecure dev key AND shows a loud warning banner in the
app (so you can't onboard a real client with weak crypto).

**Wiring changes:**
- `memory.py`: `save/load/clear_email_credentials()` (encrypted);
  `_SECRET_SETTINGS_FIELDS` keeps email overrides OUT of the plaintext settings
  table; `load_settings()` auto-populates them from encrypted storage.
- `config.py`: `email_address_override`/`email_app_password_override` checked
  before env vars (per-tenant > env fallback).
- `app.py`: login gate (`_login_page()` Login/Signup tabs, `_require_login()`);
  `get_memory()` returns tenant-scoped `AgentMemory` via `_tenant_memory(slug)`;
  sidebar shows signed-in user + logout + APP_SECRET_KEY warning; Settings page
  has per-tenant email credentials form (encrypted save/clear).
- `.gitignore`: `data/tenants/` + `data/*.db` ignored. `APP_SECRET_KEY`
  generated and set in `.env`.
- Tests: `tests/test_auth_and_crypto.py` (11), plus memory/approval additions.
  **148 total passing** as of 2026-06-21 (Invoice Generator + reminder pipeline +
  account management added since; see [[revenue-recovery-desk]] / AGENTS.md).

**Backward compatible:** single-user/local mode still works via `.env` fallback
when no per-tenant creds saved.

**IMPORTANT — orphaned old data:** the original single-user
`data/recovery_desk.db` (with earlier sample invoices/approvals/testing) is NOT
auto-migrated to any tenant; new accounts start empty. Offered to migrate it
into the first signed-up tenant on request (need the tenant slug to copy into).

**Not done yet / before scaling (clear-eyed):**
1. **AI Gemini key is still shared (operator's)** — all tenants use the one
   key, ~20 req/day cap on flash; before scaling, let clients add their own key
   (same encrypted pattern as email) or move to a billed paid tier.
2. **No billing** — Stripe Checkout is the natural next piece.
3. **Not hosted** — runs only on the user's PC. Deploy step = Render/Railway/
   Fly.io + migrate SQLite → Postgres (SQLite weak at concurrent multi-tenant
   writes).
4. **Password reset + profile update DONE** (2026-06-21): `auth.change_password`/
   `change_email` + pre-login emailed 6-digit reset code via app-level SMTP
   (`src/mailer.py`, `RRD_SMTP_*` env). **Email verification still pending**;
   Google/OIDC sign-in deferred.

**Agreed SaaS roadmap:** step 1 (strip secrets) + step 2 (multi-tenant login +
isolation) DONE. Remaining: 3 deploy/host (Postgres), 4 Stripe billing, 5 PWA
layer for mobile feel.
