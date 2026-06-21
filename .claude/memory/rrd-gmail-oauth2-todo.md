---
name: rrd-gmail-oauth2-todo
description: "Pre-scale TODO — replace Gmail App Password flow with OAuth2 (\"Sign in with Google\") for tenant email linking"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

Gmail does **not** allow regular account passwords for IMAP/SMTP (Google disabled "less secure app access" in 2022; accounts with 2-Step Verification reject plain-password login outright with a 534/535 auth error). The only way to authenticate today is a **Gmail App Password** (16-char token), which is what RRD's per-tenant draft-saving (`EMAIL_APP_PASSWORD`, IMAP) and app-level reset email (`RRD_SMTP_PASSWORD`, SMTP) both use — see [[rrd-ai-and-email-integration]] and [[rrd-smtp-domain-sender-todo]].

Current customer flow: tenant must enable 2-Step Verification on their Google account, generate an App Password, and paste it into RRD's settings. Works, but is an extra setup step and not a polished SaaS first impression.

**Better long-term approach: OAuth2 ("Connect Gmail" button)** — customer clicks Connect, approves Google's consent screen, RRD gets a token via the Gmail API; no password (app or real) ever touches RRD. More trustworthy-looking, token revocable by the customer anytime.

**Why this matters:** asking new paying customers to dig up "App Passwords" is rough onboarding friction. App passwords are fine for early/testing customers but should be replaced before broad rollout.

**How to apply / what the migration involves:**
- Register the app in Google Cloud Console, configure OAuth consent screen.
- Once past a handful of test users, the OAuth consent screen requires Google verification review (can take time — plan ahead).
- Switch from raw IMAP+password to the Gmail API (or IMAP with XOAUTH2) for draft-saving.
- Handle OAuth token storage (encrypted, like existing Fernet-encrypted creds — see [[rrd-saas-multi-tenant]]) and refresh-token renewal.

Not yet scoped in detail — revisit when onboarding moves past early/test customers.
