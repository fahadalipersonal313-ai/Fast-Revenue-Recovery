"""Phase 3 — bulk invoice generation from a parsed table.

Pure layer: column-mapped rows in, planned :class:`InvoiceData` out with a
per-row status, plus PDF rendering + zipping. No Streamlit, no DB, no network —
the caller injects ``manual_exists`` and ``get_profile`` callbacks and decides
what to persist.

Design rules (mirroring ``invoice_generator``):

* Deterministic and side-effect free given the same inputs + callbacks.
* Per-row failures never raise; they become ``status="error"`` entries so one
  bad row can't sink the whole batch.
* The per-row **amount** drives a single synthesized line item. A customer's
  saved profile only supplies branding/currency/tax/address/notes — never the
  amount, since each row's amount differs.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

from src import invoice_generator as ig

# Status values a planned row can carry.
READY = "ready"
SKIPPED_MANUAL = "skipped_manual"
ERROR = "error"

# Callback types the caller injects (kept DB-agnostic for testability).
ManualExists = Callable[[str, str], bool]
GetProfile = Callable[[str], Optional[Dict[str, Any]]]


@dataclass
class BulkResult:
    row_index: int          # 0-based position in the input rows
    customer_name: str
    invoice_number: str
    amount: float
    status: str             # READY | SKIPPED_MANUAL | ERROR
    reason: str = ""
    data: Optional[ig.InvoiceData] = None


# --- value coercion --------------------------------------------------------
def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("nan", "nat", "none", "<na>"):
        return ""
    return text


def _to_float(value: Any) -> Optional[float]:
    """Parse a money-ish cell into a float, tolerating ``$``/commas. Returns
    ``None`` when the cell is blank or not a number."""
    text = _clean_str(value)
    if not text:
        return None
    cleaned = text.replace(",", "").replace("$", "").replace("£", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_str(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
                "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# --- building one invoice --------------------------------------------------
def build_invoice_data(
    row: Dict[str, Any],
    *,
    default_issuer: Dict[str, str],
    profile: Optional[Dict[str, Any]] = None,
    default_currency: str = "$",
    default_tax: float = 0.0,
    default_description: str = "Outstanding balance",
) -> ig.InvoiceData:
    """Assemble an :class:`InvoiceData` for one mapped row.

    ``profile`` is a saved invoice-profile *schema* dict (or ``None``). It
    contributes issuer/currency/tax/address/notes; the row contributes the
    customer, identifiers, dates and the amount that becomes the line item.
    """
    schema = profile or {}
    amount = _to_float(row.get("amount_due")) or 0.0
    description = _clean_str(row.get("description")) or default_description
    currency = (schema.get("currency") or default_currency or "$")
    try:
        tax = float(schema.get("tax_rate") or default_tax or 0.0)
    except (TypeError, ValueError):
        tax = 0.0

    # Bill-to heading: prefer the explicit customer name, then company, then the
    # contact person — whichever the row actually carries.
    customer_name = _clean_str(row.get("customer_name"))
    company = _clean_str(row.get("company_name"))
    contact = _clean_str(row.get("contact_person"))
    heading = customer_name or company or contact or "Customer"

    # Compose the address block from every extra detail we captured, skipping
    # whatever is already the heading so it isn't repeated.
    addr_lines: List[str] = []
    if company and company != heading:
        addr_lines.append(company)
    if contact and contact != heading:
        addr_lines.append(f"Attn: {contact}")
    base_addr = _clean_str(row.get("address")) or schema.get("customer_address", "")
    if base_addr:
        addr_lines.append(base_addr)
    mobile = _clean_str(row.get("mobile_number"))
    if mobile:
        addr_lines.append(f"Mobile: {mobile}")

    return ig.InvoiceData(
        from_company=schema.get("from_company") or default_issuer.get("company", ""),
        from_email=schema.get("from_email") or default_issuer.get("email", ""),
        from_address=schema.get("from_address") or default_issuer.get("address", ""),
        customer_name=heading,
        customer_email=_clean_str(row.get("email")) or schema.get("customer_email", ""),
        customer_address="\n".join(addr_lines),
        invoice_number=_clean_str(row.get("invoice_number")),
        issue_date=_to_date(row.get("invoice_date")),
        due_date=_to_date(row.get("due_date")),
        currency_symbol=currency,
        line_items=[ig.LineItem(description=description, quantity=1.0,
                                unit_price=amount)],
        tax_rate_percent=tax,
        notes=schema.get("notes", ""),
    )


# --- planning a batch ------------------------------------------------------
def plan_rows(
    rows: List[Dict[str, Any]],
    *,
    manual_exists: ManualExists,
    get_profile: GetProfile,
    default_issuer: Dict[str, str],
    default_currency: str = "$",
    default_tax: float = 0.0,
) -> List[BulkResult]:
    """Classify every row into READY / SKIPPED_MANUAL / ERROR.

    ``get_profile(customer_name)`` returns that customer's saved schema dict or
    ``None``. ``manual_exists(customer_name, invoice_number)`` guards against
    clobbering invoices the user made by hand.
    """
    results: List[BulkResult] = []
    for i, row in enumerate(rows):
        # Identity falls back to company name when no explicit customer name.
        customer = _clean_str(row.get("customer_name")) or _clean_str(row.get("company_name"))
        number = _clean_str(row.get("invoice_number"))
        amount = _to_float(row.get("amount_due"))

        if not customer:
            results.append(BulkResult(i, customer, number, 0.0, ERROR,
                                      "Missing customer / company name"))
            continue
        if amount is None or amount <= 0:
            results.append(BulkResult(i, customer, number, amount or 0.0, ERROR,
                                      "Missing or non-positive amount"))
            continue
        if number and manual_exists(customer, number):
            results.append(BulkResult(i, customer, number, amount, SKIPPED_MANUAL,
                                      "A manual invoice with this number already exists"))
            continue

        try:
            data = build_invoice_data(
                row,
                default_issuer=default_issuer,
                profile=get_profile(customer),
                default_currency=default_currency,
                default_tax=default_tax,
            )
        except Exception as exc:  # noqa: BLE001 — one bad row shouldn't sink the batch
            results.append(BulkResult(i, customer, number, amount, ERROR, str(exc)))
            continue

        results.append(BulkResult(i, customer, number, amount, READY, "", data))
    return results


def summarize(results: List[BulkResult]) -> Dict[str, int]:
    counts = {READY: 0, SKIPPED_MANUAL: 0, ERROR: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(results)
    return counts


# --- rendering -------------------------------------------------------------
def render_all(ready: List[BulkResult]) -> List[Tuple[BulkResult, str, bytes]]:
    """Render every READY result to a PDF exactly once. Filenames are made
    unique within the batch so two same-named invoices don't collide in a zip.
    Rows that fail validation are downgraded to ERROR in place and skipped."""
    rendered: List[Tuple[BulkResult, str, bytes]] = []
    used: set[str] = set()
    for r in ready:
        if r.status != READY or r.data is None:
            continue
        try:
            pdf = ig.render_invoice_pdf(r.data)
        except ig.InvoiceError as exc:
            r.status = ERROR
            r.reason = str(exc)
            continue
        name = ig.suggest_filename(r.data)
        unique, k = name, 1
        while unique in used:
            unique = f"{name[:-4]}_{k}.pdf"
            k += 1
        used.add(unique)
        rendered.append((r, unique, pdf))
    return rendered


def reminder_date_for(data: ig.InvoiceData, days_after: int) -> date:
    """Per-invoice reminder date = the invoice's due date + ``days_after`` days,
    falling back to its issue date, then today, when no due date is present."""
    base = data.due_date or data.issue_date or date.today()
    return base + timedelta(days=max(int(days_after), 0))


def zip_pdfs(items: List[Tuple[BulkResult, str, bytes]]) -> bytes:
    """Bundle ``(result, filename, pdf_bytes)`` tuples into a single zip."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _result, filename, pdf in items:
            zf.writestr(filename, pdf)
    return buf.getvalue()
