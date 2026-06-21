"""Pure helper functions for dates, money, phones, emails and statuses.

These are deliberately defensive: real uploaded spreadsheets contain blanks,
stray text, mixed formats and surprises. Nothing here may raise on bad input —
the caller always gets a sensible, typed fallback.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Optional


def today() -> date:
    """Single source of truth for "now" so logic is easy to reason about."""
    return date.today()


# ---------------------------------------------------------------------------
# Missing-value handling
# ---------------------------------------------------------------------------
def is_missing(value: Any) -> bool:
    """True for None, NaN, empty strings and common null placeholders."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null", "n/a", "na", "-"}
    return False


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S",
)


def parse_date(value: Any) -> Optional[date]:
    """Parse many date representations to a ``date``; return None if unknown."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # pandas Timestamp and numpy datetime64 expose .to_pydatetime / isoformat
    to_py = getattr(value, "to_pydatetime", None)
    if callable(to_py):
        try:
            return to_py().date()
        except Exception:  # pragma: no cover - defensive
            pass
    text = str(value).strip()
    # Strip a trailing time component like "2026-01-01T00:00:00".
    text = text.replace("T", " ").split(" 00:00:00")[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def days_between(start: Optional[date], end: Optional[date]) -> Optional[int]:
    """Number of days from ``start`` to ``end`` (end - start)."""
    if start is None or end is None:
        return None
    return (end - start).days


def days_overdue(due: Optional[date], reference: Optional[date] = None) -> int:
    """Whole days a due date is past ``reference`` (today by default).

    Returns 0 when not yet due or when the due date is unknown.
    """
    ref = reference or today()
    if due is None:
        return 0
    delta = (ref - due).days
    return max(delta, 0)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def parse_amount(value: Any) -> float:
    """Parse currency-ish text ("$1,250.50", "1.250,00") into a float."""
    if is_missing(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    # Keep digits, separators and a leading sign.
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text or text in {"-", ".", ","}:
        return 0.0
    # Decide which separator is the decimal point.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")  # European style
        else:
            text = text.replace(",", "")
    elif "," in text:
        # Treat comma as decimal only when it looks like one (e.g. "12,50").
        if re.match(r"^-?\d+,\d{1,2}$", text):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def format_currency(amount: float, symbol: str = "$") -> str:
    try:
        return f"{symbol}{amount:,.2f}"
    except (TypeError, ValueError):
        return f"{symbol}0.00"


# ---------------------------------------------------------------------------
# Contact details
# ---------------------------------------------------------------------------
def clean_phone(value: Any) -> str:
    """Normalise a phone number, keeping a leading +. Empty string if none."""
    if is_missing(value):
        return ""
    text = str(value).strip()
    has_plus = text.lstrip().startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    return ("+" + digits) if has_plus else digits


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(value: Any) -> str:
    """Lower-case and trim an email; return "" if it is not a valid address."""
    if is_missing(value):
        return ""
    text = str(value).strip().lower()
    text = text.replace(" ", "")
    return text if _EMAIL_RE.match(text) else ""


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------
def normalize_status(value: Any) -> str:
    """Lower-case, collapse whitespace, strip punctuation noise."""
    if is_missing(value):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    return text.strip()


# Map many spellings to a canonical invoice payment status.
_PAID_WORDS = {"paid", "settled", "complete", "completed", "closed", "received"}
_PARTIAL_WORDS = {"partial", "partially paid", "part paid"}
_DISPUTE_WORDS = {"dispute", "disputed", "query", "queried", "contested"}


def is_paid_status(value: Any) -> bool:
    return normalize_status(value) in _PAID_WORDS


def is_partial_status(value: Any) -> bool:
    return normalize_status(value) in _PARTIAL_WORDS


def looks_disputed(*values: Any) -> bool:
    """True if any field hints the invoice is disputed."""
    for v in values:
        norm = normalize_status(v)
        if not norm:
            continue
        if norm in {"yes", "y", "true", "1"}:
            return True
        if any(word in norm for word in _DISPUTE_WORDS):
            return True
    return False


def contains_any(text: Any, keywords: list[str]) -> list[str]:
    """Return which keywords appear in the text (case-insensitive)."""
    if is_missing(text):
        return []
    haystack = str(text).lower()
    return [kw for kw in keywords if kw.lower() in haystack]
