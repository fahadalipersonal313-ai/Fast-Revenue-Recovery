"""Invoice Recovery Agent.

Pure, deterministic logic: given one normalised invoice record and the current
settings it returns an :class:`InvoiceDecision`. No money or date maths is ever
delegated to AI. Messages are produced by the communication agent and attached.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .communication_agent import build_context, generate_pair
from .config import Settings
from .models import (
    InvoiceDecision,
    InvoiceStage,
    MessageKind,
    Priority,
    RiskLevel,
)
from .utils import (
    is_paid_status,
    is_partial_status,
    looks_disputed,
    parse_amount,
    parse_date,
    today,
)

_RISK_ORDER: List[RiskLevel] = [
    RiskLevel.NONE,
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
]


def base_risk(days: int) -> RiskLevel:
    """Risk purely from days overdue, per the spec's thresholds."""
    if days <= 0:
        return RiskLevel.NONE
    if days <= 7:
        return RiskLevel.LOW
    if days <= 30:
        return RiskLevel.MEDIUM
    if days <= 60:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def _escalate(level: RiskLevel, steps: int = 1) -> RiskLevel:
    idx = min(_RISK_ORDER.index(level) + steps, len(_RISK_ORDER) - 1)
    return _RISK_ORDER[idx]


def _priority_from_score(score: float) -> Priority:
    if score >= 80:
        return Priority.CRITICAL
    if score >= 55:
        return Priority.HIGH
    if score >= 30:
        return Priority.MEDIUM
    if score > 0:
        return Priority.LOW
    return Priority.NONE


# Follow-up cadence (days) per stage.
_STAGE_INTERVAL = {
    InvoiceStage.NOT_DUE: 7,
    InvoiceStage.COURTESY_REMINDER: 5,
    InvoiceStage.STANDARD_REMINDER: 5,
    InvoiceStage.FIRM_REMINDER: 4,
    InvoiceStage.MISSED_PROMISE_FOLLOW_UP: 3,
    InvoiceStage.FINAL_INTERNAL_ESCALATION: 2,
    InvoiceStage.PAYMENT_PLAN_DISCUSSION: 7,
    InvoiceStage.HUMAN_REVIEW: 2,
}

_STAGE_MESSAGE = {
    InvoiceStage.COURTESY_REMINDER: MessageKind.COURTESY_REMINDER,
    InvoiceStage.STANDARD_REMINDER: MessageKind.STANDARD_REMINDER,
    InvoiceStage.FIRM_REMINDER: MessageKind.FIRM_REMINDER,
    InvoiceStage.MISSED_PROMISE_FOLLOW_UP: MessageKind.MISSED_PROMISE_REMINDER,
    InvoiceStage.FINAL_INTERNAL_ESCALATION: MessageKind.FINAL_ESCALATION_DRAFT,
    InvoiceStage.PAYMENT_PLAN_DISCUSSION: MessageKind.FIRM_REMINDER,
    InvoiceStage.HUMAN_REVIEW: MessageKind.STANDARD_REMINDER,
}


def analyze_invoice(
    record: Dict[str, Any],
    settings: Settings,
    reference_date: Optional[date] = None,
) -> InvoiceDecision:
    ref_date = reference_date or today()
    customer = str(record.get("customer_name") or "").strip() or "Unknown customer"
    reference = str(record.get("invoice_number") or "").strip()
    amount = parse_amount(record.get("amount_due"))
    invoice_date = parse_date(record.get("invoice_date"))
    due = parse_date(record.get("due_date"))
    promised = parse_date(record.get("promised_payment_date"))
    reminder_on = parse_date(record.get("scheduled_reminder_date"))
    status_raw = record.get("payment_status")
    reminder_count = int(parse_amount(record.get("reminder_count")) or 0)
    notes = record.get("customer_notes")

    paid = is_paid_status(status_raw)
    partial = is_partial_status(status_raw)
    disputed = looks_disputed(record.get("dispute_status"), status_raw, notes)

    reasons: List[str] = []

    # --- Paid invoices need no recovery (offer a thank-you message). ---------
    if paid and amount <= 0:
        decision = InvoiceDecision(
            customer_name=customer,
            reference=reference,
            amount=amount,
            days_overdue=0,
            is_overdue=False,
            risk_level=RiskLevel.NONE,
            stage=InvoiceStage.NOT_DUE,
            priority=Priority.NONE,
            next_action="No action needed — invoice is paid.",
            reasons=["Invoice marked paid."],
        )
        ctx = build_context(customer=customer, settings=settings, amount=amount,
                            reference=reference, invoice_date=invoice_date)
        decision.messages = generate_pair(MessageKind.PAYMENT_THANK_YOU, ctx, settings)
        return decision

    overdue = 0 if due is None else max((ref_date - due).days, 0)
    is_overdue = overdue > 0 and not paid
    missed_promise = bool(promised and promised < ref_date and not paid)
    # A user-scheduled reminder fires once its date is reached, even if the
    # invoice is not yet overdue by its due date.
    reminder_due = bool(reminder_on and reminder_on <= ref_date and not paid)

    # Conflicting info: marked paid yet a balance is overdue, or partial+overdue.
    conflicting = (paid and amount > 0) or (partial and is_overdue)

    # --- Risk -----------------------------------------------------------------
    risk = base_risk(overdue)
    if amount >= settings.high_value_threshold and risk != RiskLevel.NONE:
        risk = _escalate(risk)
        reasons.append("High-value invoice.")
    if missed_promise:
        risk = _escalate(risk)
        reasons.append("A payment promise was missed.")
    if reminder_count >= 2:
        risk = _escalate(risk)
        reasons.append(f"{reminder_count} reminders already sent without payment.")

    # --- Stage ----------------------------------------------------------------
    if disputed:
        stage = InvoiceStage.HUMAN_REVIEW
        reasons.append("Invoice is disputed — routed to human review.")
    elif not is_overdue:
        if reminder_due:
            stage = InvoiceStage.COURTESY_REMINDER
            reasons.append("Scheduled reminder date reached.")
        else:
            stage = InvoiceStage.NOT_DUE
            reasons.append("Invoice is not yet overdue.")
    elif missed_promise:
        stage = InvoiceStage.MISSED_PROMISE_FOLLOW_UP
    elif risk == RiskLevel.CRITICAL:
        stage = InvoiceStage.FINAL_INTERNAL_ESCALATION
        reasons.append("Severely overdue — final internal escalation review.")
    elif risk == RiskLevel.HIGH:
        stage = InvoiceStage.FIRM_REMINDER
    elif risk == RiskLevel.MEDIUM:
        stage = InvoiceStage.STANDARD_REMINDER
    else:
        stage = InvoiceStage.COURTESY_REMINDER

    # --- Human review triggers -----------------------------------------------
    needs_review = False
    if disputed:
        needs_review = True
    if amount >= settings.high_value_threshold:
        needs_review = True
        reasons.append("Amount is above the approval threshold.")
    if stage == InvoiceStage.FINAL_INTERNAL_ESCALATION:
        needs_review = True
    if conflicting:
        needs_review = True
        reasons.append("Conflicting payment information detected.")

    # --- Priority score -------------------------------------------------------
    score = 0.0
    score += min(overdue, 90) * 0.7
    if settings.high_value_threshold > 0:
        score += min(amount / settings.high_value_threshold, 3.0) * 18
    score += _RISK_ORDER.index(risk) * 8
    if missed_promise:
        score += 15
    score += min(reminder_count, 5) * 3
    if disputed:
        score += 10
    if reminder_due and not is_overdue:
        score += 20  # surface user-scheduled reminders even before due
    priority = _priority_from_score(score)

    # --- Next action + follow-up ---------------------------------------------
    interval = _STAGE_INTERVAL.get(stage, settings.invoice_follow_up_days)
    next_follow_up = ref_date + timedelta(days=interval)

    action_text = {
        InvoiceStage.NOT_DUE: "Monitor — no reminder required yet.",
        InvoiceStage.COURTESY_REMINDER: "Send a courtesy payment reminder.",
        InvoiceStage.STANDARD_REMINDER: "Send a standard payment reminder.",
        InvoiceStage.FIRM_REMINDER: "Send a firm payment reminder.",
        InvoiceStage.MISSED_PROMISE_FOLLOW_UP: "Follow up on the missed payment promise.",
        InvoiceStage.FINAL_INTERNAL_ESCALATION: "Prepare internal escalation draft for review.",
        InvoiceStage.PAYMENT_PLAN_DISCUSSION: "Discuss a payment plan.",
        InvoiceStage.HUMAN_REVIEW: "Send to human review before any contact.",
    }[stage]

    decision = InvoiceDecision(
        customer_name=customer,
        reference=reference,
        amount=amount,
        days_overdue=overdue,
        is_overdue=is_overdue,
        is_disputed=disputed,
        missed_promise=missed_promise,
        reminder_count=reminder_count,
        risk_level=risk,
        stage=stage,
        priority=priority,
        priority_score=round(score, 1),
        next_action=action_text,
        next_follow_up_date=next_follow_up,
        needs_human_review=needs_review,
        reasons=reasons or ["Standard overdue handling."],
    )

    # --- Messages -------------------------------------------------------------
    if stage != InvoiceStage.NOT_DUE:
        ctx = build_context(
            customer=customer,
            settings=settings,
            amount=amount,
            days_overdue=overdue,
            reference=reference,
            invoice_date=invoice_date,
            due_date=due,
            promised_date=promised,
            reminder_count=reminder_count,
            missed_promise=missed_promise,
            disputed=disputed,
        )
        kind = _STAGE_MESSAGE.get(stage, MessageKind.STANDARD_REMINDER)
        # Disputed invoices: never draft a firm chase, only a neutral note.
        if disputed:
            kind = MessageKind.STANDARD_REMINDER
        decision.messages = generate_pair(kind, ctx, settings)

    return decision
