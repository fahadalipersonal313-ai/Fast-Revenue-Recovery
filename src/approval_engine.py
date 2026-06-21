"""Human Approval Queue and the analysis orchestration that feeds it.

Nothing here ever sends a message. Approving an item only records the decision
and schedules the next follow-up task. The orchestration ``analyze_and_queue``
is shared by the Upload Center, the Daily Recovery Plan page and the scheduler
so they all behave identically.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from . import database as db
from .config import Settings
from .email_draft import save_draft
from .invoice_agent import analyze_invoice
from .lead_agent import analyze_lead
from .memory import AgentMemory
from .models import RecordType, SupervisorDecision
from .quote_agent import analyze_quote
from .supervisor_agent import AnyDecision, build_daily_plan, review
from .utils import parse_date, today

_SUBJECT_PREFIX = {
    "invoice": "Invoice",
    "quote": "Quote",
    "lead": "Follow-up",
}

_AGENTS = {
    "invoice": analyze_invoice,
    "quote": analyze_quote,
    "lead": analyze_lead,
}


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------
def _pending_exists(memory: AgentMemory, sd: SupervisorDecision) -> bool:
    row = db.query_one(
        "SELECT id FROM approvals WHERE record_type=? AND reference=? AND "
        "customer_name=? AND status='pending'",
        (sd.record_type.value, sd.reference, sd.name),
        path=memory.path,
    )
    return row is not None


def add_to_queue(memory: AgentMemory, sd: SupervisorDecision) -> Optional[int]:
    """Add a supervised recommendation to the queue, avoiding duplicates."""
    if _pending_exists(memory, sd):
        return None
    return db.execute(
        "INSERT INTO approvals"
        "(record_type, reference, customer_name, amount, priority, priority_score,"
        " reason, recommended_action, suggested_message, suggested_channel,"
        " next_follow_up_date, requires_approval) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sd.record_type.value,
            sd.reference,
            sd.name,
            sd.amount,
            sd.priority.value,
            sd.priority_score,
            sd.reason,
            sd.recommended_action,
            sd.suggested_message,
            sd.suggested_channel.value,
            sd.next_follow_up_date.isoformat() if sd.next_follow_up_date else None,
            int(sd.requires_approval),
        ),
        path=memory.path,
    )


def list_queue(
    memory: AgentMemory, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    if status:
        return db.query(
            "SELECT * FROM approvals WHERE status=? ORDER BY priority_score DESC, id DESC",
            (status,),
            path=memory.path,
        )
    return db.query(
        "SELECT * FROM approvals ORDER BY "
        "CASE status WHEN 'pending' THEN 0 ELSE 1 END, priority_score DESC, id DESC",
        path=memory.path,
    )


def _get(memory: AgentMemory, approval_id: int) -> Optional[Dict[str, Any]]:
    return db.query_one(
        "SELECT * FROM approvals WHERE id=?", (approval_id,), path=memory.path
    )


def _set_status(
    memory: AgentMemory, approval_id: int, status: str, note: str = ""
) -> None:
    db.execute(
        "UPDATE approvals SET status=?, decided_at=?, note=? WHERE id=?",
        (status, datetime.now().isoformat(timespec="seconds"), note, approval_id),
        path=memory.path,
    )


def edit_message(memory: AgentMemory, approval_id: int, new_message: str) -> None:
    db.execute(
        "UPDATE approvals SET suggested_message=? WHERE id=?",
        (new_message, approval_id),
        path=memory.path,
    )
    item = _get(memory, approval_id)
    if item:
        memory.log_decision(
            item["record_type"], item["reference"], item["customer_name"],
            "message_edited", "User edited the suggested message.",
        )


def _draft_subject(record_type: str, reference: str, customer_name: str) -> str:
    prefix = _SUBJECT_PREFIX.get(record_type, "Follow-up")
    ref_part = f" {reference}" if reference else ""
    return f"{prefix}{ref_part} — {customer_name}".strip()


def approve(
    memory: AgentMemory,
    approval_id: int,
    edited_message: Optional[str] = None,
    note: str = "",
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Approve an item: store the (possibly edited) message and schedule next task.

    This records intent only — it does NOT transmit anything itself. If
    ``settings`` has email drafting enabled, a draft (never sent) is also
    saved into the user's own email Drafts folder.

    Returns a small result dict so the UI can report what happened, e.g.
    ``{"email_draft": True}`` or ``{"email_draft": False, "email_draft_reason": "..."}``.
    """
    item = _get(memory, approval_id)
    if not item:
        return {"email_draft": False, "email_draft_reason": "Item not found."}
    if edited_message is not None and edited_message != item["suggested_message"]:
        edit_message(memory, approval_id, edited_message)
        item["suggested_message"] = edited_message
        edited = True
    else:
        edited = False

    _set_status(memory, approval_id, "approved", note)
    memory.record_message(
        record_type=item["record_type"],
        reference=item["reference"],
        customer_name=item["customer_name"],
        channel=item["suggested_channel"] or "whatsapp",
        kind="approved_outbound",
        body=item["suggested_message"] or "",
        edited=edited,
    )
    next_date = parse_date(item["next_follow_up_date"])
    memory.add_follow_up_task(
        item["record_type"], item["reference"], item["customer_name"],
        item["recommended_action"], next_date,
    )
    memory.log_decision(
        item["record_type"], item["reference"], item["customer_name"],
        "approved", note or item["recommended_action"],
    )

    draft_ok = False
    draft_reason = ""
    if settings is not None and settings.email_draft_active:
        to_addr = memory.get_customer_email(item["customer_name"])
        if not to_addr:
            draft_reason = "No email address on file for this customer."
            memory.log_decision(
                item["record_type"], item["reference"], item["customer_name"],
                "email_draft_skipped", draft_reason,
            )
        else:
            subject = _draft_subject(item["record_type"], item["reference"], item["customer_name"])
            draft_ok, draft_reason = save_draft(
                settings, to_addr, subject, item["suggested_message"] or ""
            )
            if draft_ok:
                memory.record_message(
                    record_type=item["record_type"],
                    reference=item["reference"],
                    customer_name=item["customer_name"],
                    channel="email",
                    kind="draft_saved",
                    body=item["suggested_message"] or "",
                    subject=subject,
                )
                memory.log_decision(
                    item["record_type"], item["reference"], item["customer_name"],
                    "email_draft_saved", f"Draft saved to {to_addr}.",
                )
            else:
                memory.log_decision(
                    item["record_type"], item["reference"], item["customer_name"],
                    "email_draft_failed", draft_reason,
                )

    return {"email_draft": draft_ok, "email_draft_reason": draft_reason}


def reject(memory: AgentMemory, approval_id: int, note: str = "") -> None:
    item = _get(memory, approval_id)
    _set_status(memory, approval_id, "rejected", note)
    if item:
        memory.log_decision(
            item["record_type"], item["reference"], item["customer_name"],
            "rejected", note,
        )


def postpone(
    memory: AgentMemory, approval_id: int, new_date: date, note: str = ""
) -> None:
    db.execute(
        "UPDATE approvals SET status='postponed', next_follow_up_date=?, "
        "decided_at=?, note=? WHERE id=?",
        (
            new_date.isoformat(),
            datetime.now().isoformat(timespec="seconds"),
            note,
            approval_id,
        ),
        path=memory.path,
    )
    item = _get(memory, approval_id)
    if item:
        memory.add_follow_up_task(
            item["record_type"], item["reference"], item["customer_name"],
            item["recommended_action"], new_date,
        )
        memory.log_decision(
            item["record_type"], item["reference"], item["customer_name"],
            "postponed", f"Until {new_date.isoformat()}. {note}".strip(),
        )


def mark_completed(memory: AgentMemory, approval_id: int, note: str = "") -> None:
    item = _get(memory, approval_id)
    _set_status(memory, approval_id, "completed", note)
    if item:
        memory.log_decision(
            item["record_type"], item["reference"], item["customer_name"],
            "completed", note,
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def analyze_record(
    record_type: str, record: Dict[str, Any], settings: Settings
) -> AnyDecision:
    agent = _AGENTS[record_type]
    return agent(record, settings)  # type: ignore[arg-type]


def _name_of(record_type: str, record: Dict[str, Any]) -> str:
    key = {"invoice": "customer_name", "quote": "client_name", "lead": "lead_name"}[
        record_type
    ]
    return str(record.get(key) or "").strip() or "Unknown"


def _ref_of(record_type: str, record: Dict[str, Any]) -> str:
    key = {"invoice": "invoice_number", "quote": "quote_number", "lead": "source"}[
        record_type
    ]
    return str(record.get(key) or "").strip()


def analyze_and_queue(
    memory: AgentMemory,
    settings: Settings,
    records_by_type: Dict[str, List[Dict[str, Any]]],
    enqueue: bool = True,
) -> List[SupervisorDecision]:
    """Run all agents, persist memory, optionally fill the approval queue.

    Returns the ranked daily plan. Honours duplicate-prevention: a record that
    already produced a recommendation today is recorded but not re-queued.
    """
    decisions: List[AnyDecision] = []
    plan_meta: List[tuple[AnyDecision, str, str, str]] = []

    # Clear stored recommendations for every type we're about to re-analyze, so
    # a second upload of the same file doesn't visually double the agent's
    # suggestions in the Recommendations tab. Records themselves are deduped
    # by the records table's UNIQUE constraint via save_record's ON CONFLICT.
    for record_type in records_by_type:
        if record_type in _AGENTS:
            memory.clear_recommendations(record_type)

    for record_type, rows in records_by_type.items():
        if record_type not in _AGENTS:
            continue
        for record in rows:
            try:
                decision = analyze_record(record_type, record, settings)
            except Exception:
                # A single bad row must never break the whole run.
                continue
            name = _name_of(record_type, record)
            reference = _ref_of(record_type, record)
            decisions.append(decision)
            plan_meta.append((decision, record_type, name, reference))

            # Persist the record + customer snapshot.
            email = record.get("email", "")
            phone = record.get("phone", "") if record_type == "lead" else ""
            memory.upsert_customer(name, email, phone)
            memory.save_record(
                record_type, reference, name,
                getattr(decision, "amount", getattr(decision, "estimated_value", 0)),
                str(record.get(
                    {"invoice": "payment_status", "quote": "quote_status",
                     "lead": "lead_status"}[record_type], "")),
                record,
            )

    plan = build_daily_plan(decisions, settings)

    if enqueue:
        for sd in plan:
            # Skip no-op recommendations (won/lost/paid/not due/stopped leads).
            if not sd.suggested_message and not sd.blocked_actions:
                continue
            already = memory.has_recent_recommendation(
                sd.record_type.value, sd.reference, sd.name, within_days=1
            )
            memory.record_recommendation(
                sd.record_type.value, sd.reference, sd.name, sd.amount,
                sd.priority.value, sd.priority_score, sd.recommended_action,
                sd.reason,
            )
            if not already:
                add_to_queue(memory, sd)

    return plan


def queue_counts(memory: AgentMemory) -> Dict[str, int]:
    rows = db.query(
        "SELECT status, COUNT(*) AS n FROM approvals GROUP BY status",
        path=memory.path,
    )
    return {r["status"]: r["n"] for r in rows}
