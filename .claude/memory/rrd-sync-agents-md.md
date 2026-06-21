---
name: rrd-sync-agents-md
description: "At session start, check and sync AGENTS.md changes into revenue-recovery-desk memory"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fc2f711a-c48e-49c3-ae7b-3b777783258f
---

At the start of each session touching **Revenue Recovery Desk** (`D:\revenue-recovery-desk\`),
read `D:\revenue-recovery-desk\AGENTS.md` and mirror any changes into
`C:\Users\hp\.claude\projects\C--Users-hp-Documents-Project-M\memory\revenue-recovery-desk.md`.

**Why:** The other CLI (oh my pie) updates AGENTS.md as the project's source of truth.
Keeping memory in sync ensures future sessions have current architecture, roadmap, and
layout without the user having to flag each update.

**How to apply:** First tool call: read AGENTS.md. If it differs from what's in my
`revenue-recovery-desk.md` memory, do a `replace_all` edit to mirror the full content.
This is a system of record alignment, not a cherry-pick.
