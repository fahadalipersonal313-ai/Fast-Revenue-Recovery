---
name: rrd-streamlit-cloud-gotchas
description: "Critical Streamlit Cloud quirks for RRD — ephemeral filesystem (loses tenant data on every redeploy), cache_resource reboot pattern, public-repo requirement."
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

Three things that bit us during deployment of [[rrd-deployment-live]]. Worth knowing before any future redeploy or platform decision.

## 1. Ephemeral filesystem (CRITICAL — will lose user data)
Streamlit Community Cloud uses ephemeral containers. **Every `git push` that triggers redeploy wipes the per-tenant SQLite files at `data/tenants/<slug>/recovery_desk.db`.** Resource-limit reboots and container migrations wipe them too.

**Why:** Free tier filesystem is not persisted across container rebuilds.

**Why it matters:** RRD is multi-tenant. Each signup creates an isolated SQLite. A `git push` to fix a CSS typo = every signed-up tenant's data is gone.

**Mitigation (current):** None — we're running with the foot-gun in place during validation phase. Don't push code changes once real customers exist with real data.

**Permanent fix (planned, not done):** migrate SQLite → hosted Postgres (Neon free tier 0.5GB, or Supabase 500MB). ~1 day of work updating `src/database.py` and `src/auth.py`. Do this BEFORE the first paying customer.

## 2. `@st.cache_resource` survives some redeploys, breaks shape-changes
Streamlit Cloud sometimes does a "soft" redeploy that re-imports modified `.py` files but keeps `@st.cache_resource` objects from before. If you add a new method to e.g. `AgentMemory`, the cached old-class instance won't have it → AttributeError at runtime.

**Symptom we saw:** `mem.onboarding_completed()` AttributeError despite the method being correctly committed.

**Fix:** Manage app → Reboot app (forces a clean Python process). Not amend code — the code was right.

**Pattern for future class-shape changes:** push, then manually reboot from Streamlit Cloud Manage panel.

## 3. Free tier requires PUBLIC GitHub repo
Streamlit Community Cloud free tier only deploys from public repos. Private = $20/month Streamlit Teams.

We accepted public — source is visible at https://github.com/fahadalipersonal313-ai/Fast-Revenue-Recovery. Secrets (API keys, encryption keys) stay in Streamlit Cloud's encrypted Secrets UI, never in the repo. `.gitignore` is tight (covers `.env`, `data/`, `*.db`, etc.).

**If user later wants private repo:** move to Railway (~$5/month) — supports private repos, custom domain, always-on. Decision documented but not executed.

## Related
- [[rrd-deployment-live]] — full deployment context
- [[rrd-saas-multi-tenant]] — multi-tenant architecture that the ephemeral-FS issue impacts
