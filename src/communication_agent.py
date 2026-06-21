"""Communication agent — turns a context into polite WhatsApp/email messages.

It always renders a deterministic template first, then optionally asks the AI
layer to polish the wording. The financial/date content in ``context`` is fixed
by the calling specialist agent; AI only rewrites prose.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .ai_helper import improve_message
from .config import Settings
from .message_templates import render
from .models import GeneratedMessage, MessageChannel, MessageKind
from .utils import format_currency


def _fmt_date(value: Any) -> str:
    """Human-friendly date like '05 Jun 2026', or '' if unknown."""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d %b %Y")
    return ""


def build_context(
    *,
    customer: str,
    settings: Settings,
    **details: Any,
) -> Dict[str, Any]:
    """Assemble every value the templates may reference for this record.

    The specialist agent passes whatever raw details it has (amounts, dates,
    flags, the customer's own words). We add company/signature and pre-format
    money and dates so the templates can drop them straight in. Missing details
    simply stay absent, and the templates skip the clauses that need them.
    """
    sym = settings.currency_symbol
    ctx: Dict[str, Any] = {
        "customer": (customer or "there"),
        "company": settings.company_name,
        "signature": settings.message_signature,
        "sym": sym,
    }
    ctx.update(details)

    # Money fields → formatted strings.
    if "amount" in details:
        ctx["amount_str"] = format_currency(details.get("amount") or 0, sym)
    if "budget" in details:
        ctx["budget_str"] = format_currency(details.get("budget") or 0, sym)

    # Date fields → friendly strings (key + "_str").
    for dk in ("invoice_date", "due_date", "promised_date", "quote_date",
               "last_contact_date"):
        if dk in details:
            ctx[dk + "_str"] = _fmt_date(details.get(dk))

    # Normalise a couple of derived helpers.
    ctx.setdefault("days_overdue", details.get("days_overdue", 0) or 0)
    ctx.setdefault("days_since", details.get("days_since", 0) or 0)
    ctx.setdefault("reference", details.get("reference", "") or "")
    return ctx


# Tone hints passed to the AI polisher per message kind.
_TONE = {
    MessageKind.COURTESY_REMINDER: "friendly and light",
    MessageKind.STANDARD_REMINDER: "polite and clear",
    MessageKind.FIRM_REMINDER: "professional and firm but respectful",
    MessageKind.MISSED_PROMISE_REMINDER: "understanding but clear",
    MessageKind.FINAL_ESCALATION_DRAFT: "neutral internal note",
    MessageKind.QUOTE_FOLLOW_UP: "warm and helpful",
    MessageKind.LEAD_FOLLOW_UP: "warm and enthusiastic",
    MessageKind.PRICE_OBJECTION_RESPONSE: "empathetic and reassuring",
    MessageKind.APPOINTMENT_FOLLOW_UP: "friendly and accommodating",
    MessageKind.PAYMENT_THANK_YOU: "grateful and warm",
    MessageKind.QUOTE_ACCEPTANCE_THANK_YOU: "delighted and warm",
}


def generate_message(
    kind: MessageKind,
    channel: MessageChannel,
    context: Dict[str, str],
    settings: Settings,
    use_ai: Optional[bool] = None,
) -> GeneratedMessage:
    """Render one message, optionally AI-polished."""
    rendered = render(kind, channel, context)
    body = rendered["body"]
    subject = rendered.get("subject") or None
    ai_improved = False

    want_ai = settings.ai_active if use_ai is None else use_ai
    # Never let AI touch the internal escalation draft wording.
    if want_ai and kind is not MessageKind.FINAL_ESCALATION_DRAFT:
        improved = improve_message(body, _TONE.get(kind, "polite"), settings)
        if improved:
            body = improved
            ai_improved = True

    return GeneratedMessage(
        channel=channel,
        kind=kind,
        subject=subject,
        body=body,
        ai_improved=ai_improved,
    )


def generate_pair(
    kind: MessageKind,
    context: Dict[str, str],
    settings: Settings,
    use_ai: Optional[bool] = None,
) -> List[GeneratedMessage]:
    """Generate both WhatsApp and email variants where it makes sense.

    The internal escalation draft is email-only by design.
    """
    channels = [MessageChannel.WHATSAPP, MessageChannel.EMAIL]
    if kind is MessageKind.FINAL_ESCALATION_DRAFT:
        channels = [MessageChannel.EMAIL]
    return [generate_message(kind, ch, context, settings, use_ai) for ch in channels]
