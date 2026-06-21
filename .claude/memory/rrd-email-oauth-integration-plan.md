---
name: rrd-email-oauth-integration-plan
description: Complete plan for automated Gmail + Outlook OAuth integration in RRD — supersedes the narrower gmail-only TODO
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

Plan for replacing per-tenant App Password / IMAP flow with proper "Connect Gmail" / "Connect Outlook" OAuth buttons. Supersedes [[rrd-gmail-oauth2-todo]] (which only covered Gmail and didn't address the larger Microsoft 365 / business-domain problem).

## Why this matters for the business model
RRD targets businesses, which mostly use either Google Workspace (custom domain on Gmail) or Microsoft 365 (custom domain on Outlook). Google Workspace works today via App Password (no code change), but **Microsoft 365 cannot work at all** with current code — Microsoft disabled basic auth (passwords) for IMAP/SMTP in late 2022. OAuth is the only path for Outlook customers, and it's strongly preferred for Gmail customers too (no "find your App Password" friction).

## Cost: $0 for the APIs themselves
- Google OAuth + Gmail API: free, ~1B quota units/day per project (draft creation = ~10 units → effectively unlimited)
- Microsoft Graph API + Entra ID app registration: free, generous SMB quotas
- Official libraries: `google-auth-oauthlib`+`google-api-python-client` (Google), `msal` (Microsoft)
- The real costs are dev time and Google's verification wait (Microsoft has no equivalent gate)

## Verification gate (Google only)
- `gmail.compose` is a "sensitive" scope → Google verification required for production launch (~4-6 weeks)
- Until verified: up to 100 "test users" allowed instantly — plenty for early validation
- Microsoft multi-tenant SMB apps with delegated `Mail.ReadWrite` scope have no equivalent gate

## Hard prerequisites (before either OAuth flow works)
1. Public HTTPS URL for OAuth redirect callback (e.g. `https://app.<yourdomain>.com/oauth/google/callback`). Localhost works for dev only.
2. Public privacy policy URL and terms-of-service URL (both shown on consent screens).
3. A controlled domain — ties into [[rrd-smtp-domain-sender-todo]].

## Recommended architecture
Keep existing IMAP+AppPassword as a **fallback** provider for users on Zoho/Fastmail/etc. Add two new implementations behind a thin interface:

```
EmailProvider (interface, src/email_providers/)
├── GmailOAuthProvider     ← Gmail API, refresh-token flow
├── OutlookOAuthProvider   ← Microsoft Graph, refresh-token flow
└── ImapPasswordProvider   ← existing logic, refactored from email_draft.py
```

Store encrypted refresh tokens per-tenant alongside the existing Fernet-encrypted credentials (extend the tenant settings encryption already in place — see [[rrd-saas-multi-tenant]]). One "Connect" click → refresh token good for ~6 months (Google) / indefinite (Microsoft until revoked).

## Recommended shipping order
1. **Outlook OAuth first** (1-2 days dev). No verification gate. Immediately unlocks Microsoft 365 customers who currently can't use the app at all.
2. **Gmail OAuth second** (1-2 days dev + start verification clock in parallel). 100 test users immediately, more after Google clears verification.
3. **Privacy policy + ToS page** (half day). Plain text v1 is fine.
4. **Always-on hosting with custom domain.** Railway (~$5/mo) or a $4/mo DigitalOcean droplet are cheapest reliable options. Render/Fly.io free tiers spin down when idle → breaks OAuth callbacks. Streamlit Community Cloud is free + always-on but no custom domain (subdomain only).

## Trade-off worth knowing
OAuth shifts liability: you now hold a token that can act as the user. Google verification commits you to:
- Privacy policy disclosing Gmail data use
- Possible security questionnaire (CASA assessment for *restricted* scopes — `gmail.compose` is only "sensitive" so should not trigger CASA)
- Annual re-verification

Normal SaaS bureaucratic cost, not recurring monetary.

## Related memories
- [[rrd-saas-multi-tenant]] — existing Fernet encryption to extend for refresh tokens
- [[rrd-smtp-domain-sender-todo]] — same domain dependency
- [[rrd-ai-and-email-integration]] — current IMAP draft architecture to refactor
- [[cleanops-commercial-goal]] — commercial trajectory this unblocks
