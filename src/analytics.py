"""Analytics layer — derived metrics over the per-tenant database.

Pure read functions, never mutate state. Pages and module dashboards call
these helpers instead of writing ad-hoc SQL, so the math stays in one place
and is unit-testable.

Status canonicalisation is intentionally local to this module: invoice/quote/
lead pipelines each have their own vocabulary, and analytics must collapse
those to the small set of buckets the dashboard reasons about.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from . import database as db
from .approval_engine import queue_counts
from .memory import AgentMemory
from .utils import parse_date, today

# Status vocabularies — kept in sync with the previous _stats() semantics so
# the main dashboard numbers do not move when callers migrate to this module.
PAID_STATUSES = {"paid", "settled"}
QUOTE_WON_STATUSES = {"won", "accepted", "approved", "confirmed"}
LEAD_CONVERTED_STATUSES = {"won", "converted"}


def _norm_status(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


# ---------------------------------------------------------------------------
# Top-level dashboard counters/sums.
# ---------------------------------------------------------------------------
def stats(mem: AgentMemory) -> Dict[str, Any]:
    """Numbers driving the main dashboard and sidebar.

    Stable keys: pages read this dict directly. New metrics live in dedicated
    helpers below rather than expanding this surface, so a misspelled key is
    a quick failure instead of a silently-missing chart.
    """
    counts = queue_counts(mem)
    rows = db.query(
        "SELECT record_type, amount, status FROM records "
        "WHERE record_type IN ('invoice','quote','lead')",
        path=mem.path,
    )
    invoices = [r for r in rows if r["record_type"] == "invoice"]
    quotes = [r for r in rows if r["record_type"] == "quote"]
    leads = [r for r in rows if r["record_type"] == "lead"]

    paid = [r for r in invoices if _norm_status(r["status"]) in PAID_STATUSES]
    unpaid = [r for r in invoices if _norm_status(r["status"]) not in PAID_STATUSES]
    recovered = sum(r["amount"] or 0 for r in paid)
    at_risk = sum(r["amount"] or 0 for r in unpaid) + sum(r["amount"] or 0 for r in quotes)

    pending = counts.get("pending", 0)
    handled = (counts.get("approved", 0) + counts.get("completed", 0)
               + counts.get("rejected", 0))
    total_items = pending + handled

    tasks = mem.tasks_due(date(2999, 12, 31))
    open_tasks = len(tasks)
    ref = today()
    overdue_tasks = sum(
        1 for t in tasks if (d := parse_date(t["due_date"])) and d < ref
    )
    due_today = sum(
        1 for t in tasks if (d := parse_date(t["due_date"])) and d <= ref
    )

    won = sum(1 for r in quotes if _norm_status(r["status"]) in QUOTE_WON_STATUSES)
    converted = sum(
        1 for r in leads if _norm_status(r["status"]) in LEAD_CONVERTED_STATUSES
    )

    return {
        "counts": counts,
        "pending": pending,
        "handled": handled,
        "total_items": total_items,
        "recovered": recovered,
        "at_risk": at_risk,
        "total_invoice": sum(r["amount"] or 0 for r in invoices),
        "quote_value": sum(r["amount"] or 0 for r in quotes),
        "lead_value": sum(r["amount"] or 0 for r in leads),
        "open_tasks": open_tasks,
        "overdue_tasks": overdue_tasks,
        "due_today": due_today,
        "won": won,
        "converted": converted,
        "completed": counts.get("completed", 0),
        "has_data": bool(invoices or quotes or leads),
    }


# ---------------------------------------------------------------------------
# Aging buckets — unpaid invoices grouped by days past due.
# ---------------------------------------------------------------------------
# (label, min_days_overdue inclusive, max_days_overdue inclusive). None = open.
def type_stats(mem: AgentMemory, record_type: str) -> Dict[str, Any]:
    """Numbers for one record type's own dashboard — fully independent of the
    other two types (no shared totals, no cross-type queue counts)."""
    rows = db.query(
        "SELECT amount, status FROM records WHERE record_type=?",
        (record_type,), path=mem.path,
    )
    pending = db.query(
        "SELECT COUNT(*) AS n FROM approvals WHERE record_type=? AND status='pending'",
        (record_type,), path=mem.path,
    )[0]["n"]
    completed = db.query(
        "SELECT COUNT(*) AS n FROM approvals WHERE record_type=? AND status='completed'",
        (record_type,), path=mem.path,
    )[0]["n"]

    tasks = db.query(
        "SELECT due_date FROM follow_up_tasks WHERE status='open' AND record_type=? "
        "AND due_date IS NOT NULL",
        (record_type,), path=mem.path,
    )
    ref = today()
    overdue = sum(1 for t in tasks if (d := parse_date(t["due_date"])) and d < ref)
    due_today = sum(1 for t in tasks if (d := parse_date(t["due_date"])) and d <= ref)

    if record_type == "invoice":
        won_statuses, label = PAID_STATUSES, "paid"
    elif record_type == "quote":
        won_statuses, label = QUOTE_WON_STATUSES, "won"
    else:
        won_statuses, label = LEAD_CONVERTED_STATUSES, "converted"

    closed = [r for r in rows if _norm_status(r["status"]) in won_statuses]
    open_rows = [r for r in rows if _norm_status(r["status"]) not in won_statuses]

    return {
        "record_type": record_type,
        "closed_label": label,
        "total_count": len(rows),
        "open_count": len(open_rows),
        "closed_count": len(closed),
        "open_value": sum(r["amount"] or 0 for r in open_rows),
        "closed_value": sum(r["amount"] or 0 for r in closed),
        "pending_approvals": pending,
        "completed_actions": completed,
        "overdue_tasks": overdue,
        "due_today": due_today,
        "has_data": bool(rows),
    }


_AGING_BUCKETS: tuple[tuple[str, Optional[int], Optional[int]], ...] = (
    ("Not yet due", None, 0),
    ("1–30 days",    1, 30),
    ("31–60 days",  31, 60),
    ("61–90 days",  61, 90),
    ("90+ days",    91, None),
)


def aging_buckets(
    mem: AgentMemory, *, on_date: Optional[date] = None
) -> List[Dict[str, Any]]:
    """Bucket unpaid invoices by days past due.

    Always returns every bucket (zeros included) so charts get a stable
    x-axis. Invoices without a parseable due date are skipped — they can't
    be aged. Paid/settled invoices are excluded.
    """
    ref = on_date or today()
    rows = db.query(
        "SELECT amount, status, payload_json FROM records WHERE record_type='invoice'",
        path=mem.path,
    )
    buckets = [
        {"label": lbl, "count": 0, "amount": 0.0, "_min": lo, "_max": hi}
        for lbl, lo, hi in _AGING_BUCKETS
    ]
    for row in rows:
        if _norm_status(row["status"]) in PAID_STATUSES:
            continue
        try:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        due = parse_date(payload.get("due_date"))
        if not due:
            continue
        days = (ref - due).days  # negative = not yet due
        amount = row["amount"] or 0
        for b in buckets:
            lo, hi = b["_min"], b["_max"]
            if (lo is None or days >= lo) and (hi is None or days <= hi):
                b["count"] += 1
                b["amount"] += amount
                break
    return [{"label": b["label"], "count": b["count"], "amount": b["amount"]}
            for b in buckets]


# ---------------------------------------------------------------------------
# Status breakdown — count and amount per status for any record type.
# ---------------------------------------------------------------------------
def status_breakdown(mem: AgentMemory, record_type: str) -> List[Dict[str, Any]]:
    """Group records of one type by canonical status (lower-cased, trimmed).

    Sorted by amount desc so the biggest segment leads. Missing/empty
    statuses collapse to ``unknown``.
    """
    rows = db.query(
        "SELECT amount, status FROM records WHERE record_type=?",
        (record_type,),
        path=mem.path,
    )
    by_status: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = _norm_status(r["status"]) or "unknown"
        bucket = by_status.setdefault(
            key, {"status": key, "count": 0, "amount": 0.0}
        )
        bucket["count"] += 1
        bucket["amount"] += r["amount"] or 0
    return sorted(by_status.values(), key=lambda b: b["amount"], reverse=True)


# ---------------------------------------------------------------------------
# Recovery rate over time — invoice cohorts grouped by created_at.
# ---------------------------------------------------------------------------
_PERIOD_FORMAT = {"month": "%Y-%m", "week": "%Y-%W"}


def recovery_rate_over_time(
    mem: AgentMemory,
    *,
    period: str = "month",
    periods: int = 6,
    on_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Recovery rate per invoice cohort (bucketed by record.created_at).

    Returns exactly ``periods`` entries, oldest first, ending at ``on_date``'s
    period. Each entry::

        {"period": "2026-06", "recovered": $, "outstanding": $, "rate": 0..1}

    where ``rate = recovered / (recovered + outstanding)``. Empty periods fill
    with zeros so the chart x-axis is continuous.
    """
    if period not in _PERIOD_FORMAT:
        raise ValueError(f"unknown period: {period!r} (expected 'month' or 'week')")
    if periods < 1:
        raise ValueError("periods must be >= 1")

    fmt = _PERIOD_FORMAT[period]
    ref = on_date or today()
    # Hardcoded list (small set, controlled) → safe to inline into SQL.
    paid_in = ",".join(f"'{s}'" for s in sorted(PAID_STATUSES))
    rows = db.query(
        f"""
        SELECT strftime('{fmt}', created_at) AS period,
               SUM(CASE WHEN LOWER(TRIM(COALESCE(status,''))) IN ({paid_in})
                        THEN amount ELSE 0 END) AS recovered,
               SUM(CASE WHEN LOWER(TRIM(COALESCE(status,''))) NOT IN ({paid_in})
                        THEN amount ELSE 0 END) AS outstanding
        FROM records
        WHERE record_type='invoice' AND created_at IS NOT NULL
        GROUP BY period
        """,
        path=mem.path,
    )
    by_period = {r["period"]: r for r in rows if r["period"]}

    series: List[Dict[str, Any]] = []
    for label in _period_labels(ref, period, periods):
        row = by_period.get(label) or {}
        recovered = float(row.get("recovered") or 0)
        outstanding = float(row.get("outstanding") or 0)
        total = recovered + outstanding
        series.append({
            "period": label,
            "recovered": recovered,
            "outstanding": outstanding,
            "rate": recovered / total if total > 0 else 0.0,
        })
    return series


def _period_labels(ref: date, period: str, count: int) -> List[str]:
    """``count`` strftime labels ending at ref's period, oldest first."""
    fmt = _PERIOD_FORMAT[period]
    out: List[str] = []
    cursor = ref
    if period == "month":
        for _ in range(count):
            out.append(cursor.strftime(fmt))
            y, m = cursor.year, cursor.month - 1
            if m == 0:
                y, m = y - 1, 12
            cursor = date(y, m, 1)
    else:  # week
        for _ in range(count):
            out.append(cursor.strftime(fmt))
            cursor = cursor - timedelta(days=7)
    return list(reversed(out))
