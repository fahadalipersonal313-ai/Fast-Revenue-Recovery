---
name: rrd-deployment-live
description: "RRD is LIVE — Streamlit app + Netlify landing page, both auto-deploy from public GitHub repo. URLs, pipeline, deploy config."
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

**Status as of 2026-06-21: Revenue Recovery Desk is live and accessible to anyone with the URL.** No paying customers yet — pre-launch validation phase.

## URLs
- **GitHub repo (public, free tier requirement):** https://github.com/fahadalipersonal313-ai/Fast-Revenue-Recovery
- **Streamlit app:** https://fast-revenue-recovery.streamlit.app
- **Netlify landing page:** https://revenue-recovery-desk.netlify.app

## Auto-deploy pipeline
Both surfaces deploy from the same repo on every `git push` to `main`:
- **Streamlit Cloud** rebuilds the app in ~2 min (reads `app.py`)
- **Netlify** rebuilds the landing in ~30 sec (reads `landing/` subfolder)

One push → two deploys. No manual steps.

## Netlify config (critical — set correctly after troubleshooting)
- Base directory: `/` (repo root) — NOT `landing/`
- Publish directory: `landing` (no trailing slash)
- Build command: empty
- Setting both Base AND Publish to `landing/` causes double-nesting → 404. The correct combo above was finalized after live debugging.

## Streamlit secrets (in Streamlit Cloud's Secrets UI, not the repo)
Required keys: `APP_SECRET_KEY`, `GEMINI_API_KEY`, `RRD_SMTP_HOST/PORT/USER/PASSWORD/FROM/STARTTLS/SSL`, `RRD_APP_NAME`, `EMAIL_DRAFT_ENABLED`, `EMAIL_IMAP_HOST/PORT`, `EMAIL_DRAFTS_FOLDER`, `AI_ENABLED`, `AI_PROVIDER`, `HIGH_VALUE_THRESHOLD`, `DAILY_ANALYSIS_TIME`.

**Important:** `EMAIL_ADDRESS` and `EMAIL_APP_PASSWORD` env vars were REMOVED — they used to leak operator's Gmail into every tenant's UI. Per-tenant credentials now only come from the tenant's encrypted DB row.

## Image assets
- `landing/assets/founder.png` — user's real photo (ONLY place a person's photo appears)
- `landing/assets/feature-1-invoice.png`, `feature-2-import.png`, `feature-3-ai.png` — conceptual product photography illustrations (no people), used in the 3 feature cards
- Files are stored in repo, served via Netlify CDN.

## How to deploy code changes
```bash
cd D:\revenue-recovery-desk
# edit files
git add -A && git commit -m "message" && git push
# Streamlit + Netlify both auto-redeploy
```

## Related memories
- [[rrd-streamlit-cloud-gotchas]] — ephemeral filesystem warning (CRITICAL), cache_resource reboot pattern
- [[rrd-pricing-tiers-and-gating]] — Free vs Pro implementation now live
- [[rrd-brand-rules]] — orange palette, no-competitor-names rule, photo placement
- [[revenue-recovery-desk]] — core app architecture
