# Memory index

- [CleanOps commercial goal](cleanops-commercial-goal.md) — user is building Project M into a sellable data-cleaning SaaS, phased build started 2026-06-11
- [Revenue Recovery Desk](revenue-recovery-desk.md) — Streamlit app at D:\revenue-recovery-desk, agents/models/safety architecture, run/test commands
- [RRD deployment LIVE](rrd-deployment-live.md) — Streamlit app + Netlify landing URLs, GitHub repo, auto-deploy pipeline, hosting config
- [RRD pricing & gating](rrd-pricing-tiers-and-gating.md) — Free vs Pro $15/mo live; gating module, manual upgrade procedure, Lemon Squeezy Phase 3 outstanding
- [RRD brand rules](rrd-brand-rules.md) — orange palette `#ea580c`, never name competitors, founder photo only in founder section
- [RRD Streamlit Cloud gotchas](rrd-streamlit-cloud-gotchas.md) — ephemeral filesystem (CRITICAL), cache_resource reboot pattern, public-repo requirement
- [RRD AI + email integration](rrd-ai-and-email-integration.md) — Gemini free-tier AI + email drafts; tone-variants & reply-intent features; Avast TLS/truststore, gemini-2.5-flash-lite (flash=20/day quota), stale-persisted-ai_model & Streamlit widget-state gotchas
- [RRD SaaS multi-tenant](rrd-saas-multi-tenant.md) — multi-tenant auth (PBKDF2), per-tenant SQLite isolation, Fernet-encrypted client creds, APP_SECRET_KEY; 73 tests; remaining: shared AI key, billing, hosting/Postgres, email verification
- [RRD sync AGENTS.md](rrd-sync-agents-md.md) — at session start, check and sync AGENTS.md into revenue-recovery-desk memory
- [RRD SMTP domain sender TODO](rrd-smtp-domain-sender-todo.md) — IMPORTANT before scaling: replace personal Gmail reset-email sender with a domain provider (SPF/DKIM)
- [RRD email OAuth integration plan](rrd-email-oauth-integration-plan.md) — full plan: Gmail + Outlook OAuth, costs, verification, shipping order. Supersedes the older Gmail-only TODO.
- [RRD Gmail OAuth2 TODO (older, narrower)](rrd-gmail-oauth2-todo.md) — Gmail-only note kept for the Microsoft basic-auth context; main plan now in [[rrd-email-oauth-integration-plan]]
