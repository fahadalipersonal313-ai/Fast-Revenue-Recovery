---
name: cleanops-commercial-goal
description: "User's goal for Project M (CleanOps AI) — build a sellable commercial data-cleaning SaaS"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9cc6fff0-dcbd-429b-8377-e58fba9d3a3b
---

The user wants to turn CleanOps AI (Project M, Next.js client-side data-cleaning app) into a commercial product they can sell to the public. Work began 2026-06-11.

**Why:** Their stated purpose is to earn money selling the product, so accuracy and polished/catchy presentation are explicit priorities.

**How to apply:** Build in phases. Phase 1 (completed 2026-06-11): universal cleaning engine — lib/transforms.ts (idempotent transform library), lib/profiler.ts (16 semantic column types), lib/engine.ts (pipeline orchestrating profile → transforms → dedupe), column-health UI, 26 tests green. Next is Phase 2 per ROADMAP.md: Vercel deploy, Supabase profiles table for plan state (replace the user_metadata.plan placeholder before charging money), Stripe Checkout. Keep the app free-tier friendly (100-row limit) with a Pro upsell. Keep lib/*.ts imports relative (not @/) so the node --test build resolves; existing tests must stay green.
