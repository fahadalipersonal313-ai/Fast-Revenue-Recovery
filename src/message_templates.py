"""Contextual message composition.

Rather than fixed boilerplate, each message is *assembled* from the details of
the specific record: invoice number, issue/due dates, amount, days overdue,
prior reminders, missed promises and disputes for invoices; buying signals,
objections and missing info for quotes; the enquiry, service, budget and
urgency for leads. Clauses that have no data are simply skipped.

Email is the primary, comprehensive format (subject + full body). WhatsApp is a
concise variant of the same facts. Nothing here ever contains threats, legal
claims, late-fee demands or aggressive language.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from .models import MessageChannel, MessageKind


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _g(ctx: Dict[str, Any], key: str, default: str = "") -> Any:
    v = ctx.get(key, default)
    return default if v in (None, "") else v


def _join(parts: List[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _signoff(ctx: Dict[str, Any]) -> str:
    return _g(ctx, "signature", "") or f"Best regards,\n{_g(ctx, 'company', '')}"


def _greeting(ctx: Dict[str, Any]) -> str:
    return f"Dear {_g(ctx, 'customer', 'there')},"


def _invoice_identity(ctx: Dict[str, Any]) -> str:
    """e.g. 'invoice INV-1001, issued on 05 May 2026, for $1,200.00'."""
    ref = _g(ctx, "reference")
    bits = [f"invoice {ref}" if ref else "this invoice"]
    if _g(ctx, "invoice_date_str"):
        bits.append(f"issued on {ctx['invoice_date_str']}")
    if _g(ctx, "amount_str"):
        bits.append(f"for {ctx['amount_str']}")
    return ", ".join(bits)


def _due_clause(ctx: Dict[str, Any]) -> str:
    due = _g(ctx, "due_date_str")
    days = int(ctx.get("days_overdue", 0) or 0)
    if due and days > 0:
        return f"It was due on {due} and is now {days} day{'s' if days != 1 else ''} overdue."
    if due:
        return f"It was due on {due}."
    if days > 0:
        return f"It is now {days} day{'s' if days != 1 else ''} overdue."
    return "It is now due for payment."


def _history_clause(ctx: Dict[str, Any]) -> str:
    out = []
    n = int(ctx.get("reminder_count", 0) or 0)
    if n == 1:
        out.append("This follows an earlier reminder on our side.")
    elif n > 1:
        out.append(f"Our records show {n} previous reminders, so we wanted to reach out directly.")
    if ctx.get("missed_promise") and _g(ctx, "promised_date_str"):
        out.append(f"We had also noted an expected payment around {ctx['promised_date_str']}, "
                   "which hasn't yet reached us — we understand timelines can shift.")
    elif ctx.get("missed_promise"):
        out.append("We had noted a payment was expected by the agreed date, which hasn't yet reached us.")
    return " ".join(out)


# ---------------------------------------------------------------------------
# Invoice email builders
# ---------------------------------------------------------------------------
def _courtesy(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    subject = f"Friendly reminder: invoice {ref}" if ref else "Friendly payment reminder"
    body = _join([
        _greeting(ctx),
        "I hope you're well. This is a gentle courtesy reminder regarding "
        f"{_invoice_identity(ctx)}. {_due_clause(ctx)}",
        "If payment is already arranged, please disregard this note with our thanks. "
        "Otherwise, a quick confirmation of when we can expect it would be much appreciated.",
        "If anything about the invoice is unclear, just reply to this email and we'll be glad to help.",
        "Thank you for your continued business.",
        _signoff(ctx),
    ])
    return subject, body


def _standard(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    days = int(ctx.get("days_overdue", 0) or 0)
    subject = (f"Payment reminder: invoice {ref} — {days} days overdue"
               if ref else "Payment reminder")
    body = _join([
        _greeting(ctx),
        f"I'm writing to follow up on {_invoice_identity(ctx)}. {_due_clause(ctx)}",
        _history_clause(ctx),
        "Could you let us know the expected payment date? If there's any query on the "
        "invoice, reply here and we'll resolve it quickly so it doesn't hold things up.",
        "If you've already made payment, thank you — please share the remittance details "
        "and we'll reconcile it right away.",
        "Thanks very much for your help.",
        _signoff(ctx),
    ])
    return subject, body


def _firm(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    days = int(ctx.get("days_overdue", 0) or 0)
    subject = (f"Overdue invoice {ref} — {_g(ctx, 'amount_str', 'balance')} "
               f"({days} days)" if ref else "Overdue invoice — please advise")
    body = _join([
        _greeting(ctx),
        f"I'm following up again on {_invoice_identity(ctx)}. {_due_clause(ctx)}",
        _history_clause(ctx),
        "As this has now been outstanding for some time, we'd be grateful for your prompt "
        "attention. Could you either arrange payment, or let us know a firm date so we can "
        "update your account?",
        "If there's a difficulty we should know about, we're very open to discussing a "
        "workable payment arrangement — just let us know what would help.",
        "Thank you for your cooperation.",
        _signoff(ctx),
    ])
    return subject, body


def _missed_promise(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    subject = (f"Following up on the agreed payment — invoice {ref}"
               if ref else "Following up on the agreed payment")
    promised = _g(ctx, "promised_date_str")
    promise_line = (f"We'd noted an expected payment around {promised} for {_invoice_identity(ctx)}, "
                    "which we haven't yet received." if promised
                    else f"We'd noted an expected payment for {_invoice_identity(ctx)} by the agreed "
                    "date, which we haven't yet received.")
    body = _join([
        _greeting(ctx),
        promise_line + " " + _due_clause(ctx),
        "We completely understand that plans can change. Could you let us know the revised "
        "date so we can keep your account up to date?",
        "If something has come up that affects payment, please tell us — we'd rather find a "
        "solution together than leave it open.",
        "Thank you, and we appreciate your honesty.",
        _signoff(ctx),
    ])
    return subject, body


def _escalation(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    days = int(ctx.get("days_overdue", 0) or 0)
    subject = f"[INTERNAL DRAFT — review only] Escalation: invoice {ref}"
    facts = [f"Customer: {_g(ctx, 'customer')}",
             f"Invoice: {ref or '—'}",
             f"Amount: {_g(ctx, 'amount_str', '—')}",
             f"Due: {_g(ctx, 'due_date_str', '—')} ({days} days overdue)",
             f"Reminders sent: {int(ctx.get('reminder_count', 0) or 0)}"]
    if ctx.get("missed_promise"):
        facts.append(f"Missed promised payment: {_g(ctx, 'promised_date_str', 'yes')}")
    if ctx.get("disputed"):
        facts.append("Marked DISPUTED — do not chase; resolve dispute first.")
    body = _join([
        "INTERNAL DRAFT — for human review only. Do NOT send to the customer.",
        "\n".join(facts),
        "Recommendation: review for internal escalation and decide next steps "
        "(payment plan, account hold, or continued direct follow-up). No external "
        "action has been taken and nothing has been sent.",
        _signoff(ctx),
    ])
    return subject, body


# ---------------------------------------------------------------------------
# Quote email builders
# ---------------------------------------------------------------------------
def _quote_identity(ctx: Dict[str, Any]) -> str:
    ref = _g(ctx, "reference")
    bits = [f"quote {ref}" if ref else "the quote we prepared"]
    if _g(ctx, "quote_date_str"):
        bits.append(f"sent on {ctx['quote_date_str']}")
    if _g(ctx, "amount_str"):
        bits.append(f"for {ctx['amount_str']}")
    return ", ".join(bits)


def _quote_follow_up(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    subject = f"Following up on quote {ref}" if ref else "Following up on your quote"
    days = int(ctx.get("days_since", 0) or 0)
    timing = (f"It's been {days} day{'s' if days != 1 else ''} since we sent it, so I wanted to check in."
              if days > 0 else "I wanted to check in and see how you're getting on with it.")
    interest = ""
    if ctx.get("buying_signals"):
        interest = ("From your note it sounded like this could be a good fit — "
                    "I'd love to help you take the next step.")
    info = ""
    if ctx.get("missing_information"):
        info = ("You'd asked for some additional details; I'm happy to send anything you need "
                "to make a confident decision.")
    body = _join([
        _greeting(ctx),
        f"I wanted to follow up on {_quote_identity(ctx)}. {timing}",
        interest,
        info,
        "Do you have any questions, or is there anything we could adjust — scope, timing or "
        "budget — to make it work better for you?",
        "If it's easier to talk it through, I'm glad to jump on a quick call at a time that "
        "suits you. The quote remains available whenever you're ready to proceed.",
        _signoff(ctx),
    ])
    return subject, body


def _price_objection(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    subject = (f"Re: quote {ref} — finding the right fit for your budget"
               if ref else "Options to fit your budget")
    body = _join([
        _greeting(ctx),
        "Thank you for being open about the budget — that's genuinely helpful, and I want to "
        f"make sure {_quote_identity(ctx)} works for you.",
        "The price reflects everything included, but there's usually room to tailor it. We "
        "could adjust the scope, phase the work, or look at a package that better matches "
        "what you have in mind — without compromising the result you're after.",
        "Could you share a rough budget you'd be comfortable with? I'll come back with options "
        "built around it.",
        "Happy to talk it through on a short call whenever suits — no pressure at all.",
        _signoff(ctx),
    ])
    return subject, body


def _quote_acceptance(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    subject = f"Thank you for accepting quote {ref}" if ref else "Thank you — and next steps"
    body = _join([
        _greeting(ctx),
        f"Fantastic news — thank you for accepting {_quote_identity(ctx)}! We're delighted to "
        "be working with you.",
        "Here's what happens next: I'll confirm the details, share a short plan and timeline, "
        "and let you know anything we need from you to get started.",
        "If you have any questions in the meantime, just reply here.",
        _signoff(ctx),
    ])
    return subject, body


# ---------------------------------------------------------------------------
# Lead email builders
# ---------------------------------------------------------------------------
def _lead_follow_up(ctx: Dict[str, Any]) -> Tuple[str, str]:
    service = _g(ctx, "service")
    subject = f"Re: your enquiry about {service}" if service else "Thanks for getting in touch"
    interest = (f"Thank you for reaching out about {service}." if service
                else "Thank you for reaching out.")
    echo = ""
    if _g(ctx, "customer_message"):
        snippet = str(ctx["customer_message"]).strip()
        if len(snippet) > 140:
            snippet = snippet[:137] + "…"
        echo = f"You mentioned: “{snippet}” — happy to help with exactly that."
    urgency = ""
    if ctx.get("urgency"):
        urgency = "I can see timing matters here, so I'll make this a priority."
    budget = ""
    if _g(ctx, "budget_str") and (ctx.get("budget") or 0) > 0:
        budget = (f"Based on the budget you mentioned ({ctx['budget_str']}), I can put together "
                  "options that give you the best value.")
    body = _join([
        f"Hi {_g(ctx, 'customer', 'there')},",
        interest,
        echo,
        urgency,
        budget,
        "To tailor the best options for you, could you let me know a little more about your "
        "timing and what success looks like for you? Or, if it's easier, I'm happy to set up a "
        "quick call.",
        "Looking forward to helping.",
        _signoff(ctx),
    ])
    return subject, body


def _appointment(ctx: Dict[str, Any]) -> Tuple[str, str]:
    service = _g(ctx, "service")
    subject = f"Booking your {service} appointment" if service else "Booking your appointment"
    body = _join([
        f"Hi {_g(ctx, 'customer', 'there')},",
        "Thanks again for your interest" + (f" in {service}" if service else "") +
        " — let's get you booked in.",
        "Could you share a couple of dates and times that work for you? I'll confirm straight "
        "away and send everything you need beforehand.",
        "If you'd prefer, reply with your availability and I'll do the scheduling around you.",
        _signoff(ctx),
    ])
    return subject, body


def _payment_thanks(ctx: Dict[str, Any]) -> Tuple[str, str]:
    ref = _g(ctx, "reference")
    subject = f"Thank you — payment received for invoice {ref}" if ref else "Thank you — payment received"
    body = _join([
        _greeting(ctx),
        f"Thank you! We've received your payment for {_invoice_identity(ctx)}.",
        "We really appreciate your business and look forward to working with you again. If you "
        "need a receipt or statement, just let us know.",
        _signoff(ctx),
    ])
    return subject, body


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
_EMAIL_BUILDERS: Dict[MessageKind, Callable[[Dict[str, Any]], Tuple[str, str]]] = {
    MessageKind.COURTESY_REMINDER: _courtesy,
    MessageKind.STANDARD_REMINDER: _standard,
    MessageKind.FIRM_REMINDER: _firm,
    MessageKind.MISSED_PROMISE_REMINDER: _missed_promise,
    MessageKind.FINAL_ESCALATION_DRAFT: _escalation,
    MessageKind.QUOTE_FOLLOW_UP: _quote_follow_up,
    MessageKind.PRICE_OBJECTION_RESPONSE: _price_objection,
    MessageKind.QUOTE_ACCEPTANCE_THANK_YOU: _quote_acceptance,
    MessageKind.LEAD_FOLLOW_UP: _lead_follow_up,
    MessageKind.APPOINTMENT_FOLLOW_UP: _appointment,
    MessageKind.PAYMENT_THANK_YOU: _payment_thanks,
}


def _whatsapp_version(kind: MessageKind, ctx: Dict[str, Any]) -> str:
    """A concise, friendly WhatsApp variant of the same facts."""
    name = _g(ctx, "customer", "there")
    ref = _g(ctx, "reference")
    amt = _g(ctx, "amount_str")
    days_o = int(ctx.get("days_overdue", 0) or 0)
    company = _g(ctx, "company")
    sign = f" — {company}" if company else ""

    if kind in (MessageKind.COURTESY_REMINDER, MessageKind.STANDARD_REMINDER, MessageKind.FIRM_REMINDER):
        overdue = f" ({days_o} days overdue)" if days_o > 0 else ""
        return (f"Hi {name}, a quick reminder about invoice {ref or ''} for {amt}{overdue}. "
                f"Could you let us know when we can expect payment, or reply if you have any "
                f"questions? Thank you!{sign}")
    if kind is MessageKind.MISSED_PROMISE_REMINDER:
        pd = _g(ctx, "promised_date_str")
        when = f" by {pd}" if pd else ""
        return (f"Hi {name}, we'd noted a payment{when} for invoice {ref or ''} ({amt}) that we "
                f"haven't received yet. Could you share the new expected date? Thanks!{sign}")
    if kind is MessageKind.QUOTE_FOLLOW_UP:
        return (f"Hi {name}, just following up on quote {ref or ''} ({amt}). Any questions, or "
                f"anything we can tweak to help you move forward?{sign}")
    if kind is MessageKind.PRICE_OBJECTION_RESPONSE:
        return (f"Hi {name}, totally understand on the budget. I'd love to find a package that "
                f"fits — could you share a figure you're comfortable with? Happy to tailor "
                f"quote {ref or ''} around it.{sign}")
    if kind is MessageKind.QUOTE_ACCEPTANCE_THANK_YOU:
        return (f"Hi {name}, brilliant news — thank you for accepting quote {ref or ''}! I'll "
                f"send the next steps shortly.{sign}")
    if kind is MessageKind.LEAD_FOLLOW_UP:
        service = _g(ctx, "service")
        about = f" about {service}" if service else ""
        return (f"Hi {name}, thanks for your enquiry{about}! I'd love to help — when's a good "
                f"time for a quick chat, or what else can I tell you?{sign}")
    if kind is MessageKind.APPOINTMENT_FOLLOW_UP:
        return (f"Hi {name}, let's get you booked in — what day/time suits you? I'll confirm "
                f"right away.{sign}")
    if kind is MessageKind.PAYMENT_THANK_YOU:
        return (f"Hi {name}, we've received your payment for invoice {ref or ''} — thank you so "
                f"much! A pleasure working with you.{sign}")
    return f"Hi {name}, just following up regarding {ref or 'your account'}.{sign}"


def render(
    kind: MessageKind,
    channel: MessageChannel,
    context: Dict[str, Any],
) -> Dict[str, str]:
    """Render a contextual message to {'subject': ..., 'body': ...}."""
    builder = _EMAIL_BUILDERS.get(kind)
    if builder is None:
        subject = _g(context, "company", "")
        body = _join([_greeting(context),
                      f"We wanted to follow up regarding {_g(context, 'reference', 'your account')}.",
                      _signoff(context)])
    else:
        subject, body = builder(context)

    if channel == MessageChannel.WHATSAPP and kind is not MessageKind.FINAL_ESCALATION_DRAFT:
        return {"subject": None, "body": _whatsapp_version(kind, context)}
    return {"subject": subject, "body": body}
