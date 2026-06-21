---
name: rrd-pricing-tiers-and-gating
description: "RRD pricing model (Free + $15/mo Pro), gating module, current limits, manual upgrade procedure, Lemon Squeezy Phase 3 outstanding."
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

## Decided pricing — two tiers
- **Free** — $0/forever. 50 records/month (invoices+quotes+leads combined), 10 distinct clients, single PDF invoice only, top-5 recommendations/day, no AI, no bulk operations, no Excel reports/exports.
- **Pro** — $15/month or $144/year (save 20%). Unlimited records & clients, AI message tone variants, AI reply intent detection, bulk invoice generation, bulk file uploads, Excel reports, priority email support.

Currency: **USD** throughout (app default `currency_symbol="$"`, landing page in `$`). User may change tenant-level currency in Settings.

## Positioning
Cheaper than enterprise tools that start at $250+/month. Target = sole traders, freelancers, micro-agencies, tradespeople — i.e. anyone tracking invoices in a spreadsheet without accounting software. See [[rrd-brand-rules]] for the no-competitor-names rule.

## Implementation (live)
- `src/gating.py` — centralizes limits (`FREE_RECORD_LIMIT_PER_MONTH=50`, `FREE_CLIENT_LIMIT=10`, `FREE_RECOMMENDATION_DAILY_LIMIT=5`) and helpers (`is_pro`, `record_count_this_month`, `client_count`, `can_upload_records`).
- `auth.users` table has `tier` (default `'free'`) + `pro_until` (ISO datetime, NULL=lifetime) columns added via migration.
- `auth.User` dataclass carries `tier` and `pro_until`; signup/login/find_user_by_id load them.
- `auth.set_tier(user_id, tier, pro_until=None)` is the manual-upgrade hook (also future Lemon Squeezy webhook target).
- Gates applied at UI flow level only — data layer is unguarded so tests/scripts aren't affected.

## Gated features (all show `ui.upgrade_card(...)` for Free users)
- **Upload page** — pre-counts incoming rows; blocks if would breach 50/month.
- **Invoice Generator → Bulk subtab** — blocked entirely for Free.
- **Reports page** — blocked entirely for Free.
- **AI features in Approval Queue** — tone variants + reply intent gated by `_ai_unlocked()` helper (requires Pro AND `ai_available(settings)`).
- **Sidebar** shows live `Free plan · X/50 records left this month` chip + orange "✨ Upgrade to Pro" button linking to `https://revenue-recovery-desk.netlify.app/#pricing`. Pro users see gradient "✨ Pro plan" chip instead.

## Manual upgrade procedure (until Phase 3 ships)
```python
from src import auth
auth.set_tier(user_id=3, tier="pro")  # lifetime
# or with expiry:
from datetime import datetime, timedelta
auth.set_tier(3, "pro", pro_until=(datetime.utcnow() + timedelta(days=30)).isoformat())
# downgrade:
auth.set_tier(3, "free")
```

## Phase 3 outstanding — Lemon Squeezy automated billing
Decided processor: **Lemon Squeezy** (chosen over Stripe because LS handles global VAT/sales-tax as merchant of record — worth the ~5% + 50¢ fees vs Stripe's 2.9% + 30¢ + tax-compliance burden).

Not yet built. Requires user to:
1. Create Lemon Squeezy account
2. Create $15/month Pro product
3. Provide API key + product ID + signing secret

Then build: webhook receiver that calls `auth.set_tier(user_id, "pro", pro_until=<billing_period_end>)` on successful payment events, flips back to `free` on cancellation/failure.

Estimated ~2 hours of work once LS account + creds are ready.

## Related
- [[rrd-deployment-live]] — live URLs, deployment pipeline
- [[rrd-saas-multi-tenant]] — auth model the tier columns extend
- [[rrd-email-oauth-integration-plan]] — separate Pro feature roadmap
