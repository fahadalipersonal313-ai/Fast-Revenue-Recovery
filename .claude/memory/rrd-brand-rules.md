---
name: rrd-brand-rules
description: "RRD brand and positioning rules — orange/white palette, no competitor names, founder-photo-only placement, target market positioning."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

Decisions made during the landing-page + app polish work. Apply these by default in any future UI/marketing work for Revenue Recovery Desk.

## Color palette — warm orange + white
Primary: `#ea580c` (orange-600). Hover: `#c2410c`. Light variants: `#fb923c`, `#fdba74`. Tints: `#fff7ed`, `#ffedd5`. Accent: `#f59e0b` (amber-500). Hero/CTA gradients combine orange→amber→rose.

**Why:** chosen by user during the landing page redesign. Previously was indigo `#4f46e5`; full sweep done across `src/ui.py` and `landing/styles.css`. Distinguishes RRD from the violet/blue palette common in B2B SaaS (Stripe, Linear, Notion).

**How to apply:** any new component, new CSS, new gradient defaults to orange family. Do NOT introduce indigo, violet, blue, or green unless the user explicitly asks.

## Never name competitors in user-facing copy
**Rule:** the landing page and app must never mention competitors by name (Chaser, Satago, Upflow, InvoiceSherpa, etc.).

**Why:** user explicitly removed all "Chaser" references after I had used the name in the landing page ("Why us, not Chaser"). User's stated reason: doesn't want to mention them.

**How to apply:** when positioning against competitors, use generic phrasing — "enterprise tools in this space start at $250+/month" not "Chaser starts at $199/month." It's fine to discuss competitors WITH the user in chat (for strategy) — just never put names in shipped copy.

## Founder photo placement — only in the founder section
User's real photo appears ONLY in the "Why this exists" founder section of the landing page (`landing/assets/founder.png`). Nowhere else — not in the hero, not in feature cards, not in testimonials.

**Why:** user tried generating 10 ChatGPT photos for the landing page, then immediately reversed course ("it was a bad idea"). The agreed compromise: their real photo in founder area only, plus 3 conceptual product illustrations (no people) for feature cards.

**How to apply:** if adding new sections to the landing or app, do NOT add photos of people. If visual is needed, prefer abstract gradient cards, emoji-on-gradient illustrations, or conceptual product photography (objects/scenes, no faces). For founder section only, the real founder photo is fine.

## Target market positioning
Built for the **bottom of the AR-automation market**: sole traders, freelancers, micro-agencies, tradespeople. People tracking invoices in spreadsheets without accounting software like Xero/QuickBooks. Distinguishing line: "no accounting software needed."

Pricing wedge documented in [[rrd-pricing-tiers-and-gating]] — $0/$15 vs enterprise $200+/mo.

## Related
- [[rrd-deployment-live]] — where these rules apply (Streamlit app + Netlify landing)
- [[rrd-pricing-tiers-and-gating]] — current pricing tied to positioning
