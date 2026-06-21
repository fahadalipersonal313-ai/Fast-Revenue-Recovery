"""Lead Recovery Agent.

Scores a sales lead from its message and metadata, assigns a temperature, and
prepares a follow-up — while always explaining *why* the score landed where it
did. Clearly-lost leads are stopped.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .communication_agent import build_context, generate_pair
from .config import Settings
from .models import LeadDecision, LeadTemperature, MessageKind, Priority
from .quote_agent import BUYING_SIGNALS, PRICE_OBJECTION_WORDS
from .utils import (
    contains_any,
    normalize_status,
    parse_amount,
    parse_date,
    today,
)

URGENCY_WORDS = ["urgent", "asap", "today", "tomorrow", "immediately", "right away",
                 "this week", "deadline", "soon"]
BUDGET_WORDS = ["budget", "afford", "spend", "price range", "willing to pay", "ready to pay"]
MISSING_INFO_WORDS = ["more info", "details", "not sure", "question", "clarify", "?"]

_LOST = {"lost", "dead", "not interested", "closed lost", "unqualified", "spam"}
_WON = {"won", "converted", "closed won", "customer", "client"}


def temperature_for(score: int, lost: bool) -> LeadTemperature:
    if lost or score < 15:
        return LeadTemperature.DEAD
    if score >= 70:
        return LeadTemperature.HOT
    if score >= 40:
        return LeadTemperature.WARM
    return LeadTemperature.COLD


def analyze_lead(
    record: Dict[str, Any],
    settings: Settings,
    reference_date: Optional[date] = None,
) -> LeadDecision:
    ref_date = reference_date or today()
    name = str(record.get("lead_name") or "").strip() or "Unknown lead"
    reference = str(record.get("source") or "").strip()
    budget = parse_amount(record.get("budget"))
    last_contact = parse_date(record.get("last_contact_date"))
    status = normalize_status(record.get("lead_status"))
    message = record.get("customer_message")
    replies = record.get("previous_replies")

    lost = status in _LOST
    won = status in _WON

    days_since = 0 if last_contact is None else max((ref_date - last_contact).days, 0)

    signals = sorted(set(contains_any(message, BUYING_SIGNALS)))
    urgency = bool(contains_any(message, URGENCY_WORDS))
    budget_signal = bool(contains_any(message, BUDGET_WORDS)) or budget > 0
    price_sensitive = bool(contains_any(message, PRICE_OBJECTION_WORDS))
    missing_info = bool(contains_any(message, MISSING_INFO_WORDS))

    # --- Transparent scoring --------------------------------------------------
    score = 0
    explanation: List[str] = []

    pts = min(len(signals), 6) * 8
    if pts:
        score += pts
        explanation.append(f"+{pts} for buying signals ({', '.join(signals)}).")
    if urgency:
        score += 15
        explanation.append("+15 for urgency language.")
    if budget_signal:
        score += 15
        explanation.append("+15 for a budget signal.")
    if normalize_status(replies) and normalize_status(replies) not in {"no", "none"}:
        score += 10
        explanation.append("+10 for prior replies (engaged).")
    if budget >= settings.high_value_threshold and budget > 0:
        score += 10
        explanation.append("+10 for a high estimated value.")
    if price_sensitive:
        score -= 5
        explanation.append("-5 for price sensitivity.")
    if days_since > 14:
        score -= 10
        explanation.append("-10 for going cold (>14 days since contact).")
    elif days_since > 7:
        score -= 5
        explanation.append("-5 for slowing down (>7 days since contact).")

    if lost:
        explanation.append("Lead status is lost/dead → scored as dead.")
    score = max(0, min(score, 100))
    if not explanation:
        explanation.append("No strong signals; baseline cold lead.")

    temperature = temperature_for(score, lost)

    # --- Stop rule ------------------------------------------------------------
    stop = lost
    reasons: List[str] = []
    if stop:
        reasons.append("Lead is lost — follow-ups stopped.")
        return LeadDecision(
            lead_name=name, reference=reference, estimated_value=budget,
            days_since_contact=days_since, buying_signals=signals, urgency=urgency,
            budget_signal=budget_signal, price_sensitive=price_sensitive,
            missing_information=missing_info, lead_score=score,
            temperature=LeadTemperature.DEAD, priority=Priority.NONE,
            next_action="No action — lead is lost.", stop_follow_ups=True,
            score_explanation=explanation, reasons=reasons,
        )

    # --- Priority -------------------------------------------------------------
    priority = {
        LeadTemperature.HOT: Priority.HIGH,
        LeadTemperature.WARM: Priority.MEDIUM,
        LeadTemperature.COLD: Priority.LOW,
        LeadTemperature.DEAD: Priority.NONE,
    }[temperature]

    # --- Action + message -----------------------------------------------------
    if price_sensitive:
        kind = MessageKind.PRICE_OBJECTION_RESPONSE
        action = "Address price sensitivity and reframe value."
    elif urgency or temperature == LeadTemperature.HOT:
        kind = MessageKind.LEAD_FOLLOW_UP
        action = "Reply quickly — hot lead with intent."
    elif "appointment" in signals or "book" in signals:
        kind = MessageKind.APPOINTMENT_FOLLOW_UP
        action = "Offer to book an appointment."
    else:
        kind = MessageKind.LEAD_FOLLOW_UP
        action = "Send a follow-up to re-engage."

    interval = {
        LeadTemperature.HOT: 1,
        LeadTemperature.WARM: settings.lead_follow_up_days,
        LeadTemperature.COLD: 7,
        LeadTemperature.DEAD: 0,
    }[temperature]
    next_follow_up = ref_date + timedelta(days=interval) if interval else None

    needs_review = budget >= settings.high_value_threshold and budget > 0
    if won:
        reasons.append("Lead appears converted — confirm before further sales contact.")
        needs_review = True

    decision = LeadDecision(
        lead_name=name, reference=reference, estimated_value=budget,
        days_since_contact=days_since, buying_signals=signals, urgency=urgency,
        budget_signal=budget_signal, price_sensitive=price_sensitive,
        missing_information=missing_info, lead_score=score, temperature=temperature,
        priority=priority, priority_score=float(score),
        next_action=action, next_follow_up_date=next_follow_up,
        stop_follow_ups=False, needs_human_review=needs_review,
        score_explanation=explanation, reasons=reasons or ["Standard lead follow-up."],
    )

    ctx = build_context(
        customer=name, settings=settings, amount=budget, budget=budget,
        days_since=days_since, reference=reference,
        service=str(record.get("service_requested") or "").strip(),
        customer_message=message, urgency=urgency, buying_signals=signals,
    )
    decision.messages = generate_pair(kind, ctx, settings)
    return decision
