"""Free-vs-Pro feature gating.

Centralizes every Free-tier limit and the is-this-user-allowed check, so the
limits live in exactly one place (changing one number doesn't require hunting
through app.py).

Gating philosophy:
- We never silently break a flow. Free users get a friendly upgrade prompt
  (handled by the UI layer) — not an exception, not a hidden no-op.
- Limits only apply to UI flows. The underlying data layer stays unguarded
  so tests, scripts, and future automation aren't affected by tier checks.
- A user with ``tier='pro'`` and a still-future ``pro_until`` (or NULL) is
  Pro. Past-due pro_until silently demotes them to free at read time.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from . import database as db

if TYPE_CHECKING:  # avoid runtime circulars
    from .auth import User
    from .memory import AgentMemory

# ---------------------------------------------------------------------------
# Limits — change these in ONE place if pricing/positioning shifts.
# ---------------------------------------------------------------------------
FREE_RECORD_LIMIT_PER_MONTH = 50      # invoices + quotes + leads combined
FREE_CLIENT_LIMIT = 10                # distinct customer names
FREE_RECOMMENDATION_DAILY_LIMIT = 5   # top-N shown to free users
FREE_AI_REFINE_LIMIT_PER_MONTH = 10   # interactive AI refines (fine-tune +
                                      # tone variants) per month on Free; Pro is
                                      # unlimited. Paid "Phase 2" tier tunes this.


def is_pro(user: "User") -> bool:
    """True when the user has an active Pro subscription. Lifetime pro
    (pro_until is NULL) counts as Pro. Past-due pro_until counts as Free."""
    if user.tier != "pro":
        return False
    if not user.pro_until:
        return True  # lifetime pro / manual grant with no expiry
    try:
        expires = datetime.fromisoformat(user.pro_until.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True  # malformed timestamp — fail-open so a paying user isn't blocked
    return expires > datetime.utcnow().replace(tzinfo=expires.tzinfo)


def record_count_this_month(mem: "AgentMemory") -> int:
    """Count of records (any type) created in the current calendar month."""
    rows = db.query(
        "SELECT COUNT(*) AS n FROM records WHERE created_at >= ?",
        (datetime.utcnow().strftime("%Y-%m-01"),),
        path=mem.path,
    )
    return int(rows[0]["n"]) if rows else 0


def client_count(mem: "AgentMemory") -> int:
    """Count of distinct customers tracked across all records."""
    rows = db.query(
        "SELECT COUNT(DISTINCT customer_name) AS n FROM records "
        "WHERE customer_name IS NOT NULL AND customer_name != ''",
        path=mem.path,
    )
    return int(rows[0]["n"]) if rows else 0


def records_remaining_this_month(user: "User", mem: "AgentMemory") -> int | None:
    """How many more records this user can add this month. Returns None for
    Pro (unlimited). Returns 0 (or negative) when at/past limit."""
    if is_pro(user):
        return None
    return FREE_RECORD_LIMIT_PER_MONTH - record_count_this_month(mem)


def clients_remaining(user: "User", mem: "AgentMemory") -> int | None:
    """How many more clients this user can track. Returns None for Pro."""
    if is_pro(user):
        return None
    return FREE_CLIENT_LIMIT - client_count(mem)


def ai_refines_this_month(mem: "AgentMemory") -> int:
    """Interactive AI refines used this month (Fine-tune + tone variants)."""
    return mem.ai_refine_usage_this_month()


def ai_refine_allowed(user: "User", mem: "AgentMemory") -> bool:
    """Can this user run another interactive AI refine right now? Pro is
    unlimited; Free is capped at FREE_AI_REFINE_LIMIT_PER_MONTH per month."""
    if is_pro(user):
        return True
    return ai_refines_this_month(mem) < FREE_AI_REFINE_LIMIT_PER_MONTH


def ai_refines_remaining(user: "User", mem: "AgentMemory") -> int | None:
    """Refines left this month. None for Pro (unlimited); 0 when a Free user is
    at the cap."""
    if is_pro(user):
        return None
    return max(0, FREE_AI_REFINE_LIMIT_PER_MONTH - ai_refines_this_month(mem))


def record_ai_refine(user: "User", mem: "AgentMemory") -> None:
    """Count one interactive AI refine against the Free monthly cap. No-op for
    Pro so the counter reflects only Free-tier consumption."""
    if is_pro(user):
        return
    mem.increment_ai_refine_usage()


def can_upload_records(user: "User", mem: "AgentMemory",
                       incoming_count: int) -> tuple[bool, str]:
    """Pre-check before processing a file upload. Returns (allowed, reason).
    Reason is empty string when allowed."""
    if is_pro(user):
        return True, ""
    used = record_count_this_month(mem)
    if used + incoming_count > FREE_RECORD_LIMIT_PER_MONTH:
        return False, (
            f"This upload would put you over the Free plan's "
            f"{FREE_RECORD_LIMIT_PER_MONTH}-record monthly limit "
            f"(you have {used} already; this file has {incoming_count} more). "
            f"Upgrade to Pro for unlimited records — or split the file."
        )
    return True, ""


def feature_locked_reason(feature: str) -> str:
    """One-liner shown on the upgrade card next to a locked feature."""
    return {
        "ai":           "AI-drafted follow-ups and reply intent detection",
        "bulk_invoice": "Bulk invoice generation from spreadsheets",
        "bulk_upload":  "Bulk import of invoices, quotes & leads",
        "reports":      "Excel reports and exports",
        "unlimited":    "Unlimited records and clients",
    }.get(feature, "this feature")
