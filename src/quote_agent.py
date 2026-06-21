"""Quote Recovery Agent.

Given a normalised quotation record it decides whether the quote needs a
follow-up, how urgent it is, and which message to prepare. Won/lost quotes are
explicitly left alone.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .communication_agent import build_context, generate_pair
from .config import Settings
from .models import (
    MessageKind,
    Priority,
    QuoteClass,
    QuoteDecision,
)
from .utils import (
    contains_any,
    normalize_status,
    parse_amount,
    parse_date,
    today,
)

BUYING_SIGNALS = [
    "price", "quote", "urgent", "available", "book", "appointment", "today",
    "tomorrow", "package", "deadline", "budget", "ready", "proceed", "go ahead",
    "when can", "how soon", "interested",
]

PRICE_OBJECTION_WORDS = [
    "expensive", "too much", "cheaper", "discount", "lower price", "high price",
    "out of budget", "can't afford", "cost too", "pricey",
]

MISSING_INFO_WORDS = [
    "more info", "details", "spec", "specification", "send me", "clarify",
    "question", "not sure", "need to know",
]

_WON = {"won", "accepted", "approved", "confirmed", "closed won", "sold"}
_LOST = {"lost", "rejected", "declined", "cancelled", "closed lost", "dead"}


def follow_up_priority(days_since: int) -> str:
    """Map elapsed days to the spec's follow-up bands."""
    if days_since <= 0:
        return "none"
    if days_since <= 2:
        return "soft follow up"
    if days_since <= 7:
        return "normal follow up"
    if days_since <= 14:
        return "stronger follow up"
    return "final check in"


def analyze_quote(
    record: Dict[str, Any],
    settings: Settings,
    reference_date: Optional[date] = None,
) -> QuoteDecision:
    ref_date = reference_date or today()
    client = str(record.get("client_name") or "").strip() or "Unknown client"
    reference = str(record.get("quote_number") or "").strip()
    amount = parse_amount(record.get("quote_amount"))
    quote_date = parse_date(record.get("quote_date"))
    last_follow_up = parse_date(record.get("last_follow_up_date"))
    follow_up_count = int(parse_amount(record.get("follow_up_count")) or 0)
    status = normalize_status(record.get("quote_status"))
    message = record.get("customer_message")

    reasons: List[str] = []

    # Use the most recent of (quote sent / last follow-up) as the clock start.
    anchor = max([d for d in (quote_date, last_follow_up) if d], default=None)
    days_since = 0 if anchor is None else max((ref_date - anchor).days, 0)

    buying_signals = contains_any(message, BUYING_SIGNALS)
    price_objection = bool(contains_any(message, PRICE_OBJECTION_WORDS))
    missing_info = bool(contains_any(message, MISSING_INFO_WORDS))

    # --- Won / lost: no further action ---------------------------------------
    if status in _WON:
        decision = QuoteDecision(
            client_name=client, reference=reference, amount=amount,
            days_since_sent=days_since, follow_up_count=follow_up_count,
            classification=QuoteClass.WON, priority=Priority.NONE,
            next_action="No action — quote won.",
            reasons=["Quote already won."],
        )
        ctx = build_context(customer=client, settings=settings, amount=amount,
                            reference=reference, quote_date=quote_date)
        decision.messages = generate_pair(
            MessageKind.QUOTE_ACCEPTANCE_THANK_YOU, ctx, settings
        )
        return decision
    if status in _LOST:
        return QuoteDecision(
            client_name=client, reference=reference, amount=amount,
            days_since_sent=days_since, follow_up_count=follow_up_count,
            classification=QuoteClass.LOST, priority=Priority.NONE,
            next_action="No action — quote lost.",
            reasons=["Quote marked lost."],
        )

    # --- Classification -------------------------------------------------------
    if price_objection:
        classification = QuoteClass.REVIEW_REQUIRED
        reasons.append("Price objection detected — needs a tailored response.")
    elif days_since <= 7:
        classification = QuoteClass.ACTIVE
    elif days_since <= 14:
        classification = QuoteClass.WARM
    else:
        classification = QuoteClass.COLD

    if buying_signals:
        reasons.append("Buying signals: " + ", ".join(sorted(set(buying_signals))) + ".")
        if classification == QuoteClass.COLD:
            classification = QuoteClass.WARM
    if missing_info:
        reasons.append("Client asked for more information.")

    band = follow_up_priority(days_since)
    reasons.append(f"{days_since} days since last contact → {band}.")

    # --- Priority score -------------------------------------------------------
    score = 0.0
    score += min(days_since, 30) * 1.5
    if settings.high_value_threshold > 0:
        score += min(amount / settings.high_value_threshold, 3.0) * 15
    score += len(set(buying_signals)) * 6
    if price_objection:
        score += 12
    score = min(score, 100)
    if score >= 70:
        priority = Priority.HIGH
    elif score >= 40:
        priority = Priority.MEDIUM
    elif score > 0:
        priority = Priority.LOW
    else:
        priority = Priority.NONE

    # --- Next action / message kind ------------------------------------------
    if price_objection:
        kind = MessageKind.PRICE_OBJECTION_RESPONSE
        action = "Respond to the price objection."
    elif band == "final check in":
        kind = MessageKind.QUOTE_FOLLOW_UP
        action = "Send a final check-in on the quote."
    else:
        kind = MessageKind.QUOTE_FOLLOW_UP
        action = f"Send a {band}."

    interval = {
        "soft follow up": 2,
        "normal follow up": settings.quote_follow_up_days,
        "stronger follow up": 5,
        "final check in": 7,
        "none": settings.quote_follow_up_days,
    }[band]
    next_follow_up = ref_date + timedelta(days=interval)

    # High-value quotes still get a human-review flag for safety.
    needs_review = amount >= settings.high_value_threshold and price_objection

    decision = QuoteDecision(
        client_name=client,
        reference=reference,
        amount=amount,
        days_since_sent=days_since,
        follow_up_count=follow_up_count,
        classification=classification,
        buying_signals=sorted(set(buying_signals)),
        price_objection=price_objection,
        missing_information=missing_info,
        priority=priority,
        priority_score=round(score, 1),
        next_action=action,
        next_follow_up_date=next_follow_up,
        needs_human_review=needs_review,
        reasons=reasons,
    )

    ctx = build_context(
        customer=client, settings=settings, amount=amount,
        days_since=days_since, reference=reference, quote_date=quote_date,
        follow_up_count=follow_up_count, buying_signals=sorted(set(buying_signals)),
        price_objection=price_objection, missing_information=missing_info,
        customer_message=message,
    )
    decision.messages = generate_pair(kind, ctx, settings)
    return decision
