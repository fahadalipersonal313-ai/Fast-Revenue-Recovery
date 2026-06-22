"""Detect and map messy spreadsheet headers onto our canonical field names.

Uploaded files use wildly different column names ("Amount", "Total Due",
"Balance"). We try to auto-detect each canonical field from a list of aliases;
anything we cannot confidently match is reported back so the UI can ask the
user to map it manually. Original columns are never discarded.
"""

from __future__ import annotations

import difflib
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Canonical fields per record type, each with the header aliases we recognise.
INVOICE_FIELDS: Dict[str, List[str]] = {
    "customer_name": ["customer name", "customer", "client", "client name", "name", "account"],
    "invoice_number": ["invoice number", "invoice no", "invoice #", "invoice", "inv no", "number", "ref"],
    "invoice_date": ["invoice date", "issue date", "date", "created", "billed date"],
    "due_date": ["due date", "due", "payment due", "deadline"],
    "amount_due": ["amount due", "amount", "total", "total due", "balance", "outstanding", "value"],
    "payment_status": ["payment status", "status", "paid", "state"],
    "last_reminder_date": ["last reminder date", "last reminder", "reminder date"],
    "reminder_count": ["reminder count", "reminders", "reminders sent", "num reminders"],
    "promised_payment_date": ["promised payment date", "payment date", "promised date", "promise date", "promise"],
    "dispute_status": ["dispute status", "disputed", "dispute", "query"],
    "customer_notes": ["customer notes", "notes", "comments", "remarks"],
    "email": ["email", "e-mail", "email address", "mail", "customer email"],
    "Contact Person": ["Contact person", "person", "focal person", "representative", "customer representative"],
}

QUOTE_FIELDS: Dict[str, List[str]] = {
    "client_name": ["client name", "client", "customer", "customer name", "name"],
    "quote_number": ["quote number", "quote no", "quote #", "quote", "number", "ref", "quotation"],
    "quote_amount": ["quote amount", "amount", "total", "value", "price"],
    "quote_date": ["quote date", "date", "sent date", "created", "issued"],
    "quote_status": ["quote status", "status", "state", "stage"],
    "last_follow_up_date": ["last follow up date", "last follow up", "follow up date", "followup"],
    "follow_up_count": ["follow up count", "follow ups", "followups", "num follow ups"],
    "customer_message": ["customer message", "message", "reply", "response", "enquiry"],
    "customer_notes": ["customer notes", "notes", "comments", "remarks"],
    "email": ["email", "e-mail", "email address", "mail", "customer email", "client email"],
}

LEAD_FIELDS: Dict[str, List[str]] = {
    "lead_name": ["lead name", "lead", "name", "customer", "contact", "client"],
    "source": ["source", "channel", "origin", "lead source"],
    "phone": ["phone", "mobile", "number", "contact number", "tel", "whatsapp"],
    "email": ["email", "e-mail", "email address", "mail"],
    "customer_message": ["customer message", "message", "enquiry", "inquiry", "request"],
    "service_requested": ["service requested", "service", "interest", "product", "requirement"],
    "budget": ["budget", "amount", "value", "spend", "price range"],
    "last_contact_date": ["last contact date", "last contact", "contacted", "last contacted"],
    "next_follow_up_date": ["next follow up date", "next follow up", "follow up", "next contact"],
    "lead_status": ["lead status", "status", "state", "stage"],
    "previous_replies": ["previous replies", "replies", "responses", "conversation"],
    "notes": ["notes", "comments", "remarks"],
}

# Bulk invoice *generation* (Invoice Generator → "Bulk from file" tab). Richer
# bill-to detail than the recovery invoice set, and a separate learned-alias
# pool so teaching here doesn't reshape the Upload Center invoice mapping.
BULK_INVOICE_FIELDS: Dict[str, List[str]] = {
    "customer_name": INVOICE_FIELDS["customer_name"],
    "company_name": ["company name", "company", "business name", "organisation",
                     "organization", "firm", "business", "vendor"],
    "contact_person": ["contact person", "contact name", "contact", "attention",
                       "attn", "person", "representative"],
    "email": INVOICE_FIELDS["email"],
    "mobile_number": ["mobile number", "mobile", "phone", "phone number", "cell",
                      "cellphone", "contact number", "tel", "telephone", "whatsapp"],
    "address": ["address", "billing address", "customer address", "client address",
                "location", "street"],
    "invoice_number": INVOICE_FIELDS["invoice_number"],
    "amount_due": INVOICE_FIELDS["amount_due"],
    "invoice_date": INVOICE_FIELDS["invoice_date"],
    "due_date": INVOICE_FIELDS["due_date"],
    "description": ["description", "details", "item", "service", "line item",
                    "particulars", "work done", "narrative"],
}

# Bulk quote *generation* (Quote Generator → "Bulk from file" tab). Mirrors the
# bulk-invoice set but carries quote identifiers/dates instead of invoice ones.
BULK_QUOTE_FIELDS: Dict[str, List[str]] = {
    "customer_name": QUOTE_FIELDS["client_name"],
    "company_name": BULK_INVOICE_FIELDS["company_name"],
    "contact_person": BULK_INVOICE_FIELDS["contact_person"],
    "email": QUOTE_FIELDS["email"],
    "mobile_number": BULK_INVOICE_FIELDS["mobile_number"],
    "address": BULK_INVOICE_FIELDS["address"],
    "quote_number": QUOTE_FIELDS["quote_number"],
    "amount_due": QUOTE_FIELDS["quote_amount"],
    "quote_date": QUOTE_FIELDS["quote_date"],
    "valid_until": ["valid until", "valid till", "expiry", "expiry date",
                    "expires", "valid to", "quote valid until"],
    "description": BULK_INVOICE_FIELDS["description"],
}

FIELD_SETS = {
    "invoice": INVOICE_FIELDS,
    "quote": QUOTE_FIELDS,
    "lead": LEAD_FIELDS,
    "invoice_bulk": BULK_INVOICE_FIELDS,
    "quote_bulk": BULK_QUOTE_FIELDS,
}

# Fields that the agents genuinely need to function.
REQUIRED_FIELDS = {
    "invoice": ["customer_name", "due_date", "amount_due"],
    "quote": ["client_name", "quote_date"],
    "lead": ["lead_name"],
}


def _norm(text: str) -> str:
    return " ".join(str(text).strip().lower().replace("_", " ").split())


def detect_mapping(
    columns: List[str],
    record_type: str,
    learned: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """Return (field -> source column) and the list of unmapped canonical fields.

    Matching order: exact alias (built-in + learned) → fuzzy fallback. A source
    column is only used once. ``learned`` is the per-record-type alias memory so
    the detector improves with every confirmed mapping.
    """
    fields = FIELD_SETS[record_type]
    learned = learned or {}
    normalized = {col: _norm(col) for col in columns}
    mapping: Dict[str, str] = {}
    used: set[str] = set()

    def aliases_for(field: str) -> set[str]:
        built_in = {_norm(a) for a in fields[field]}
        return built_in | {_norm(a) for a in learned.get(field, [])}

    # Pass 1: exact alias match (built-in + learned).
    for field in fields:
        alias_norms = aliases_for(field)
        for col, norm in normalized.items():
            if col in used:
                continue
            if norm in alias_norms:
                mapping[field] = col
                used.add(col)
                break

    # Pass 2: fuzzy match for whatever is still missing.
    for field in fields:
        if field in mapping:
            continue
        candidates = [c for c in columns if c not in used]
        if not candidates:
            break
        best_col, best_score = None, 0.0
        for col in candidates:
            for alias in aliases_for(field):
                score = difflib.SequenceMatcher(None, alias, normalized[col]).ratio()
                if score > best_score:
                    best_score, best_col = score, col
        if best_col and best_score >= 0.82:
            mapping[field] = best_col
            used.add(best_col)

    unmapped = [f for f in fields if f not in mapping]
    return mapping, unmapped


# ---------------------------------------------------------------------------
# Header fingerprints + profile matching
# ---------------------------------------------------------------------------
def header_signature(columns: List[str]) -> str:
    """A stable fingerprint of a file's headers (order-independent)."""
    return "|".join(sorted(_norm(c) for c in columns if _norm(c)))


def signature_similarity(sig_a: str, sig_b: str) -> float:
    """Jaccard overlap of two header signatures (0..1)."""
    set_a = {p for p in sig_a.split("|") if p}
    set_b = {p for p in sig_b.split("|") if p}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def match_profile(
    profiles: List[dict], columns: List[str], threshold: float = 0.6
) -> Optional[dict]:
    """Pick the best-matching saved profile for these headers, if confident."""
    sig = header_signature(columns)
    best, best_score = None, 0.0
    for prof in profiles:
        score = signature_similarity(sig, prof.get("header_signature", ""))
        if score > best_score:
            best_score, best = score, prof
    if best and best_score >= threshold:
        best = {**best, "match_score": round(best_score, 2)}
        return best
    return None


# ---------------------------------------------------------------------------
# Status vocabulary normalisation (per-client dictionaries)
# ---------------------------------------------------------------------------
# Canonical tokens the agents understand, with default word guesses.
STATUS_CATEGORIES = {
    "invoice": ["paid", "unpaid", "partial", "disputed", "open"],
    "quote": ["won", "lost", "open"],
    "lead": ["won", "lost", "open"],
}

_DEFAULT_STATUS_GUESS = {
    "paid": {"paid", "settled", "complete", "completed", "closed", "received", "cleared"},
    "unpaid": {"unpaid", "outstanding", "o/s", "os", "due", "overdue", "open", "pending", "owing", "not paid"},
    "partial": {"partial", "partially paid", "part paid", "part-paid"},
    "disputed": {"disputed", "dispute", "query", "queried", "contested", "hold"},
    "won": {"won", "accepted", "approved", "confirmed", "sold", "converted", "closed won"},
    "lost": {"lost", "rejected", "declined", "cancelled", "dead", "closed lost", "not interested"},
    "open": {"open", "sent", "new", "active", "in progress", "contacted", "draft", "pending"},
}


def guess_status_category(value: str, record_type: str) -> str:
    """Best-guess canonical token for a raw status value."""
    norm = _norm(value)
    if not norm:
        return ""
    valid = STATUS_CATEGORIES[record_type]
    for token in valid:
        if norm in _DEFAULT_STATUS_GUESS.get(token, set()):
            return token
    # Substring fallback.
    for token in valid:
        if any(w in norm for w in _DEFAULT_STATUS_GUESS.get(token, set())):
            return token
    return ""


def suggest_status_map(values: List[str], record_type: str) -> Dict[str, str]:
    """Suggest a {raw_value: canonical_token} map for the unique status values."""
    out: Dict[str, str] = {}
    for v in values:
        norm = _norm(v)
        if norm and norm not in out:
            out[norm] = guess_status_category(v, record_type)
    return out


def apply_status_map(series: pd.Series, status_map: Dict[str, str]) -> pd.Series:
    """Translate raw status values to canonical tokens using a client map.

    Unmapped values are passed through unchanged so nothing is silently lost.
    """
    if not status_map:
        return series
    lookup = {_norm(k): v for k, v in status_map.items() if v}

    def _translate(v):
        token = lookup.get(_norm(v))
        return token if token else v

    return series.map(_translate)


def missing_required(mapping: Dict[str, str], record_type: str) -> List[str]:
    """Required canonical fields that are still not mapped."""
    return [f for f in REQUIRED_FIELDS[record_type] if f not in mapping]


def apply_mapping(
    df: pd.DataFrame, mapping: Dict[str, str]
) -> pd.DataFrame:
    """Produce a processed copy with canonical column names.

    The original frame is left untouched; canonical columns are added so the
    agents can read consistent names while the raw upload is preserved
    elsewhere.
    """
    processed = pd.DataFrame(index=df.index)
    for field, source in mapping.items():
        if source in df.columns:
            processed[field] = df[source]
    # Ensure every canonical field exists, even if empty, so agents can rely on it.
    return processed
