"""Bulk quotation generation from a parsed table.

Mirrors :mod:`bulk_invoice` exactly, but produces :class:`quote_generator.QuoteData`
per row. Pure layer: column-mapped rows in, planned quotes out with a per-row
status, plus PDF rendering + zipping. No Streamlit, no DB, no network.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

from src import quote_generator as qg
from src.bulk_invoice import _clean_str, _to_date, _to_float  # shared coercion

READY = "ready"
SKIPPED_MANUAL = "skipped_manual"
ERROR = "error"

ManualExists = Callable[[str, str], bool]
GetProfile = Callable[[str], Optional[Dict[str, Any]]]


@dataclass
class BulkQuoteResult:
    row_index: int
    customer_name: str
    quote_number: str
    amount: float
    status: str
    reason: str = ""
    data: Optional[qg.QuoteData] = None


def build_quote_data(
    row: Dict[str, Any],
    *,
    default_issuer: Dict[str, str],
    profile: Optional[Dict[str, Any]] = None,
    default_currency: str = "$",
    default_tax: float = 0.0,
    default_description: str = "Proposed work",
) -> qg.QuoteData:
    """Assemble a :class:`QuoteData` for one mapped row."""
    schema = profile or {}
    amount = _to_float(row.get("amount_due")) or 0.0
    description = _clean_str(row.get("description")) or default_description
    currency = (schema.get("currency") or default_currency or "$")
    try:
        tax = float(schema.get("tax_rate") or default_tax or 0.0)
    except (TypeError, ValueError):
        tax = 0.0

    customer_name = _clean_str(row.get("customer_name"))
    company = _clean_str(row.get("company_name"))
    contact = _clean_str(row.get("contact_person"))
    heading = customer_name or company or contact or "Customer"

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

    return qg.QuoteData(
        from_company=schema.get("from_company") or default_issuer.get("company", ""),
        from_email=schema.get("from_email") or default_issuer.get("email", ""),
        from_address=schema.get("from_address") or default_issuer.get("address", ""),
        customer_name=heading,
        customer_email=_clean_str(row.get("email")) or schema.get("customer_email", ""),
        customer_address="\n".join(addr_lines),
        quote_number=_clean_str(row.get("quote_number")),
        quote_date=_to_date(row.get("quote_date")),
        valid_until=_to_date(row.get("valid_until")),
        currency_symbol=currency,
        line_items=[qg.LineItem(description=description, quantity=1.0,
                                unit_price=amount)],
        tax_rate_percent=tax,
        notes=schema.get("notes", ""),
    )


def plan_rows(
    rows: List[Dict[str, Any]],
    *,
    manual_exists: ManualExists,
    get_profile: GetProfile,
    default_issuer: Dict[str, str],
    default_currency: str = "$",
    default_tax: float = 0.0,
) -> List[BulkQuoteResult]:
    """Classify every row into READY / SKIPPED_MANUAL / ERROR."""
    results: List[BulkQuoteResult] = []
    for i, row in enumerate(rows):
        customer = _clean_str(row.get("customer_name")) or _clean_str(row.get("company_name"))
        number = _clean_str(row.get("quote_number"))
        amount = _to_float(row.get("amount_due"))

        if not customer:
            results.append(BulkQuoteResult(i, customer, number, 0.0, ERROR,
                                           "Missing customer / company name"))
            continue
        if amount is None or amount <= 0:
            results.append(BulkQuoteResult(i, customer, number, amount or 0.0, ERROR,
                                           "Missing or non-positive amount"))
            continue
        if number and manual_exists(customer, number):
            results.append(BulkQuoteResult(i, customer, number, amount, SKIPPED_MANUAL,
                                           "A manual quote with this number already exists"))
            continue

        try:
            data = build_quote_data(
                row,
                default_issuer=default_issuer,
                profile=get_profile(customer),
                default_currency=default_currency,
                default_tax=default_tax,
            )
        except Exception as exc:  # noqa: BLE001 — one bad row shouldn't sink the batch
            results.append(BulkQuoteResult(i, customer, number, amount, ERROR, str(exc)))
            continue

        results.append(BulkQuoteResult(i, customer, number, amount, READY, "", data))
    return results


def summarize(results: List[BulkQuoteResult]) -> Dict[str, int]:
    counts = {READY: 0, SKIPPED_MANUAL: 0, ERROR: 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(results)
    return counts


def render_all(ready: List[BulkQuoteResult]) -> List[Tuple[BulkQuoteResult, str, bytes]]:
    """Render every READY result to a PDF exactly once, with unique filenames."""
    rendered: List[Tuple[BulkQuoteResult, str, bytes]] = []
    used: set[str] = set()
    for r in ready:
        if r.status != READY or r.data is None:
            continue
        try:
            pdf = qg.render_quote_pdf(r.data)
        except qg.QuoteError as exc:
            r.status = ERROR
            r.reason = str(exc)
            continue
        name = qg.suggest_filename(r.data)
        unique, k = name, 1
        while unique in used:
            unique = f"{name[:-4]}_{k}.pdf"
            k += 1
        used.add(unique)
        rendered.append((r, unique, pdf))
    return rendered


def zip_pdfs(items: List[Tuple[BulkQuoteResult, str, bytes]]) -> bytes:
    """Bundle ``(result, filename, pdf_bytes)`` tuples into a single zip."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _result, filename, pdf in items:
            zf.writestr(filename, pdf)
    return buf.getvalue()
