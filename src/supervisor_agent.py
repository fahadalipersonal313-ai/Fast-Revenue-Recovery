"""Supervisor Agent — the safety gate over every specialist recommendation.

It selects the right specialist output, validates it against business and
safety rules, decides whether human approval is required, and never lets the
system auto-approve anything sensitive. It also assembles the ranked daily
recovery plan.
"""

from __future__ import annotations

from typing import List, Union

from .config import Settings
from .models import (
    InvoiceDecision,
    InvoiceStage,
    LeadDecision,
    MessageChannel,
    Priority,
    QuoteDecision,
    RecordType,
    SupervisorDecision,
)

AnyDecision = Union[InvoiceDecision, QuoteDecision, LeadDecision]

_PRIORITY_RANK = {
    Priority.CRITICAL: 4,
    Priority.HIGH: 3,
    Priority.MEDIUM: 2,
    Priority.LOW: 1,
    Priority.NONE: 0,
}

# Actions the supervisor must NEVER auto-approve. These always need a human.
NEVER_AUTO_APPROVE = [
    "automatic final escalation",
    "legal threats",
    "invoice write off",
    "disputed invoice action",
    "high value sensitive communication",
    "payment status change",
]


def _pick_message(decision: AnyDecision) -> tuple[str, MessageChannel]:
    if not decision.messages:
        return "", MessageChannel.WHATSAPP
    # Prefer the WhatsApp variant for quick action; fall back to the first.
    for msg in decision.messages:
        if msg.channel == MessageChannel.WHATSAPP:
            return msg.body, MessageChannel.WHATSAPP
    first = decision.messages[0]
    return first.body, first.channel


def review(decision: AnyDecision, settings: Settings) -> SupervisorDecision:
    """Validate one specialist decision and produce a supervised recommendation."""
    blocked: List[str] = []
    safety: List[str] = []
    requires_approval = True  # safe default — v1 never sends without approval.

    message, channel = _pick_message(decision)

    if isinstance(decision, InvoiceDecision):
        name, reference, amount = decision.customer_name, decision.reference, decision.amount
        action, reason = decision.next_action, "; ".join(decision.reasons)
        priority, score = decision.priority, decision.priority_score
        follow_up = decision.next_follow_up_date

        if decision.is_disputed:
            blocked.append("disputed invoice action")
            safety.append("Disputed — no chasing message may be sent without review.")
        if decision.stage == InvoiceStage.FINAL_INTERNAL_ESCALATION:
            blocked.append("automatic final escalation")
            safety.append("Final escalation is an internal draft only — needs a human.")
        if amount >= settings.high_value_threshold:
            blocked.append("high value sensitive communication")
            safety.append("Above the approval threshold.")
        rec_type = RecordType.INVOICE

    elif isinstance(decision, QuoteDecision):
        name, reference, amount = decision.client_name, decision.reference, decision.amount
        action, reason = decision.next_action, "; ".join(decision.reasons)
        priority, score = decision.priority, decision.priority_score
        follow_up = decision.next_follow_up_date
        if amount >= settings.high_value_threshold and decision.price_objection:
            blocked.append("high value sensitive communication")
            safety.append("High-value quote with a price objection — review wording.")
        rec_type = RecordType.QUOTE

    else:  # LeadDecision
        name, reference, amount = decision.lead_name, decision.reference, decision.estimated_value
        action, reason = decision.next_action, "; ".join(decision.reasons)
        priority, score = decision.priority, decision.priority_score
        follow_up = decision.next_follow_up_date
        if decision.stop_follow_ups:
            safety.append("Lead is lost — follow-ups stopped.")
        rec_type = RecordType.LEAD

    # A low-priority routine touch with no blocked actions could in principle be
    # pre-cleared, but v1 policy keeps a human in the loop for everything that
    # results in an outbound message.
    if not message:
        requires_approval = bool(blocked) or decision.needs_human_review

    return SupervisorDecision(
        record_type=rec_type,
        name=name,
        reference=reference,
        amount=amount,
        priority=priority,
        priority_score=score,
        recommended_action=action,
        reason=reason,
        suggested_message=message,
        suggested_channel=channel,
        next_follow_up_date=follow_up,
        requires_approval=requires_approval,
        blocked_actions=sorted(set(blocked)),
        safety_notes=safety,
    )


def build_daily_plan(
    decisions: List[AnyDecision], settings: Settings
) -> List[SupervisorDecision]:
    """Review all decisions and return them ranked highest-priority first."""
    supervised = [review(d, settings) for d in decisions]
    supervised.sort(
        key=lambda s: (_PRIORITY_RANK.get(s.priority, 0), s.priority_score),
        reverse=True,
    )
    return supervised
