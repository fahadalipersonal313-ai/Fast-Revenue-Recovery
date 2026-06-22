"""Standardized, downloadable spreadsheet templates.

One source of truth for the column headers a user should use when preparing a
file for bulk invoice/quote generation. The same canonical labels are reused by
the manual generators, so what a user types by hand and what they upload in bulk
always line up. Pure: builds in-memory ``.xlsx`` bytes, no disk writes.
"""

from __future__ import annotations

from io import BytesIO
from typing import Dict, List

import pandas as pd

# Canonical headers (display order) for each template. These map cleanly onto
# ``column_mapper.BULK_INVOICE_FIELDS`` / ``BULK_QUOTE_FIELDS`` aliases, so an
# unedited template auto-detects every column on upload.
INVOICE_TEMPLATE_HEADERS: List[str] = [
    "Customer Name", "Company Name", "Contact Person", "Email", "Mobile Number",
    "Address", "Invoice Number", "Amount", "Invoice Date", "Due Date", "Description",
]

QUOTE_TEMPLATE_HEADERS: List[str] = [
    "Customer Name", "Company Name", "Contact Person", "Email", "Mobile Number",
    "Address", "Quote Number", "Amount", "Quote Date", "Valid Until", "Description",
]

# A single, illustrative example row so the template is self-explanatory.
_INVOICE_EXAMPLE = [
    "Acme Corp", "Acme Corporation Ltd", "Priya Shah", "priya@acme.example",
    "+1 555 010 2020", "12 Market St, Springfield", "INV-1001", 1450.00,
    "2026-06-01", "2026-06-30", "Website redesign — phase 1",
]
_QUOTE_EXAMPLE = [
    "Bright Studios", "Bright Studios LLC", "Tom Walsh", "tom@brightstudios.example",
    "+1 555 010 3030", "88 Loft Ave, Riverside", "Q-2001", 5400.00,
    "2026-06-10", "2026-07-10", "Brand photography package",
]

_TEMPLATES: Dict[str, Dict] = {
    "invoice": {"headers": INVOICE_TEMPLATE_HEADERS, "example": _INVOICE_EXAMPLE,
                "sheet": "Invoices"},
    "quote": {"headers": QUOTE_TEMPLATE_HEADERS, "example": _QUOTE_EXAMPLE,
              "sheet": "Quotes"},
}


def template_headers(kind: str) -> List[str]:
    """Return the canonical headers for ``kind`` ("invoice" or "quote")."""
    return list(_TEMPLATES[kind]["headers"])


def build_template_xlsx(kind: str, *, with_example: bool = True) -> bytes:
    """Build an ``.xlsx`` with the standardized headers (and one example row).

    ``kind`` is "invoice" or "quote". The example row makes the expected format
    obvious; pass ``with_example=False`` for a headers-only sheet.
    """
    spec = _TEMPLATES[kind]
    rows = [spec["example"]] if with_example else []
    df = pd.DataFrame(rows, columns=spec["headers"])
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=spec["sheet"])
    return buf.getvalue()


def template_filename(kind: str) -> str:
    return f"{kind}_template.xlsx"
