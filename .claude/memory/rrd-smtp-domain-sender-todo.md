---
name: rrd-smtp-domain-sender-todo
description: IMPORTANT before scaling RRD — replace personal Gmail SMTP sender with a domain email provider
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c1a4e36-50e5-4670-b50b-15cf0e5bbc13
---

**IMPORTANT / high priority before scaling.** The RRD "Forgot password" reset-code email (app-level SMTP, `RRD_SMTP_*` in `D:\revenue-recovery-desk\.env`) currently sends from the user's personal Gmail `fahadali.personal313@gmail.com` using a Gmail App Password. This is the shared app-wide sender for ALL customers (one sender delivers reset codes to every tenant; see `src/mailer.py` and `app.py` reset flow).

Fine for testing / first clients, but MUST change before scaling:
- **Deliverability:** mail from personal Gmail to other inboxes lands in spam without proper SPF/DKIM.
- **Sending limits:** regular Gmail caps ~500 outbound/day.
- **Branding/trust:** customers see a personal Gmail as the From address.

**How to apply:** move to a domain email provider (SendGrid / Postmark / Amazon SES) with `noreply@<yourdomain>` as `RRD_SMTP_FROM`, set up SPF + DKIM. Update the `RRD_SMTP_*` vars accordingly.

Related: [[rrd-ai-and-email-integration]], [[rrd-saas-multi-tenant]], [[cleanops-commercial-goal]].
