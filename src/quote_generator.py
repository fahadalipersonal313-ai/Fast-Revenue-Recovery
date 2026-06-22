"""Manual + bulk quotation PDF generator.

Mirrors :mod:`invoice_generator` exactly — pure functions, deterministic, no
Streamlit/DB/network — but produces a *quotation* instead of an invoice:

* Title reads "QUOTATION".
* The right-hand meta block shows Quote #, Quote date and a "Valid until" date
  (instead of an issue/due date pair).
* :func:`to_record` projects the quote into the canonical *quote record* dict
  the quote-recovery pipeline (quote agent → daily plan → approval queue)
  consumes, so a generated quote can immediately be tracked for follow-up.

The :class:`LineItem`, :class:`CustomField` dataclasses and the premium
neutral-charcoal styling are shared with :mod:`invoice_generator` so the two
documents never drift apart visually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Reuse the invoice building blocks so the two generators stay in lock-step.
from src.invoice_generator import (  # noqa: F401  (re-exported for callers)
    CustomField,
    InvoiceError,
    LineItem,
    _money,
    _scaled_image,
)


class QuoteError(InvoiceError):
    """Raised when the caller-supplied quote data is invalid."""


@dataclass
class QuoteData:
    """Everything the renderer needs to draw one quotation."""

    # Issuer (your company)
    from_company: str
    from_email: str = ""
    from_address: str = ""

    # Customer
    customer_name: str = ""
    customer_email: str = ""
    customer_address: str = ""

    # Identifiers + dates
    quote_number: str = ""
    quote_date: Optional[date] = None
    valid_until: Optional[date] = None

    # Money
    currency_symbol: str = "$"
    line_items: List[LineItem] = field(default_factory=list)
    tax_rate_percent: float = 0.0

    # Free-form
    notes: str = ""

    # User-added extra fields, shown in an "Additional details" grid.
    custom_fields: List[CustomField] = field(default_factory=list)

    # Branding images (raw bytes, PNG/JPG).
    letterhead_png: Optional[bytes] = None
    signature_png: Optional[bytes] = None
    signature_label: str = ""


def _validate(data: QuoteData) -> None:
    # Company name is only mandatory when there's no letterhead — a letterhead
    # already carries the company name/contact details.
    if not data.from_company.strip() and not data.letterhead_png:
        raise QuoteError("Your company name is required (or upload a letterhead).")
    if not data.customer_name.strip():
        raise QuoteError("Customer name is required.")
    if not data.line_items:
        raise QuoteError("At least one line item is required.")
    if data.tax_rate_percent < 0:
        raise QuoteError("Tax rate cannot be negative.")
    for i, item in enumerate(data.line_items, start=1):
        if not item.description.strip():
            raise QuoteError(f"Line item {i}: description is required.")
        if item.quantity <= 0:
            raise QuoteError(f"Line item {i}: quantity must be > 0.")
        if item.unit_price < 0:
            raise QuoteError(f"Line item {i}: unit price cannot be negative.")


def compute_totals(data: QuoteData) -> dict:
    """Return subtotal/tax/total. Pure arithmetic — no PDF involved."""
    subtotal = round(sum(li.amount for li in data.line_items), 2)
    tax = round(subtotal * (data.tax_rate_percent / 100.0), 2)
    return {"subtotal": subtotal, "tax": tax, "total": round(subtotal + tax, 2)}


def render_quote_pdf(data: QuoteData) -> bytes:
    """Render ``data`` as a quotation PDF and return the raw bytes.

    Raises ``QuoteError`` if the input is invalid. Never writes to disk.
    """
    _validate(data)
    totals = compute_totals(data)

    INK = colors.HexColor("#111827")
    BODY = colors.HexColor("#374151")
    MUTED = colors.HexColor("#6b7280")
    ACCENT = colors.HexColor("#111827")
    HAIRLINE = colors.HexColor("#e5e7eb")
    ZEBRA = colors.HexColor("#f9fafb")
    HEAD_BG = colors.HexColor("#111827")

    sym = data.currency_symbol
    margin = 0.7 * inch
    content_w = LETTER[0] - 2 * margin

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Quotation {data.quote_number}" if data.quote_number else "Quotation",
        author=data.from_company,
    )

    base = getSampleStyleSheet()["BodyText"]

    def style(name, **kw):
        return ParagraphStyle(name, parent=base, **kw)

    title_st = style("title", fontName="Helvetica-Bold", fontSize=30, leading=32,
                     textColor=ACCENT, spaceAfter=0)
    company_st = style("company", fontName="Helvetica-Bold", fontSize=13, leading=17,
                       textColor=INK)
    small_st = style("small", fontName="Helvetica", fontSize=9, leading=13,
                     textColor=MUTED)
    label_st = style("label", fontName="Helvetica-Bold", fontSize=8, leading=11,
                     textColor=MUTED)
    meta_label_st = style("meta_label", fontName="Helvetica-Bold", fontSize=8,
                          leading=12, textColor=MUTED, alignment=2)
    meta_value_st = style("meta_value", fontName="Helvetica-Bold", fontSize=10.5,
                          leading=14, textColor=INK, alignment=2)
    cust_st = style("cust", fontName="Helvetica-Bold", fontSize=12, leading=15,
                    textColor=INK)
    body_st = style("body", fontName="Helvetica", fontSize=9.5, leading=13,
                    textColor=BODY)

    story: list = []

    if data.letterhead_png:
        banner = _scaled_image(data.letterhead_png, max_w=content_w, max_h=1.5 * inch)
        if banner is not None:
            banner.hAlign = "CENTER"
            story.append(banner)
            story.append(Spacer(1, 14))

    # When a letterhead banner is shown, its artwork already carries the
    # company name/address/email, so we don't repeat them here.
    left_cell = [Paragraph("QUOTATION", title_st)]
    if not data.letterhead_png:
        left_cell.append(Spacer(1, 6))
        if data.from_company:
            left_cell.append(Paragraph(data.from_company, company_st))
        if data.from_address:
            left_cell.append(Paragraph(data.from_address.replace("\n", "<br/>"), small_st))
        if data.from_email:
            left_cell.append(Paragraph(data.from_email, small_st))

    meta_rows = []
    if data.quote_number:
        meta_rows.append([Paragraph("QUOTE #", meta_label_st),
                          Paragraph(data.quote_number, meta_value_st)])
    if data.quote_date:
        meta_rows.append([Paragraph("DATE", meta_label_st),
                          Paragraph(data.quote_date.isoformat(), meta_value_st)])
    if data.valid_until:
        meta_rows.append([Paragraph("VALID UNTIL", meta_label_st),
                          Paragraph(data.valid_until.isoformat(), meta_value_st)])
    meta_w = 2.7 * inch
    if meta_rows:
        right_cell = Table(meta_rows, colWidths=[1.0 * inch, 1.7 * inch])
        right_cell.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        right_cell = Paragraph("", small_st)

    header = Table([[left_cell, right_cell]],
                   colWidths=[content_w - meta_w, meta_w])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width=content_w, thickness=2.5, color=ACCENT,
                            spaceBefore=0, spaceAfter=0))
    story.append(Spacer(1, 16))

    # --- Quote for ----------------------------------------------------------
    story.append(Paragraph("QUOTE FOR", label_st))
    story.append(Spacer(1, 3))
    story.append(Paragraph(data.customer_name, cust_st))
    if data.customer_address:
        story.append(Paragraph(data.customer_address.replace("\n", "<br/>"), small_st))
    if data.customer_email:
        story.append(Paragraph(data.customer_email, small_st))
    story.append(Spacer(1, 18))

    extra = [(cf.label.strip(), cf.value.strip()) for cf in data.custom_fields
             if cf.label.strip() and cf.value.strip()]
    if extra:
        story.append(Paragraph("ADDITIONAL DETAILS", label_st))
        story.append(Spacer(1, 4))
        cf_rows = [[Paragraph(lbl, label_st), Paragraph(val, body_st)] for lbl, val in extra]
        cf_tbl = Table(cf_rows, colWidths=[1.8 * inch, content_w - 1.8 * inch])
        cf_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(cf_tbl)
        story.append(Spacer(1, 18))

    rows = [["DESCRIPTION", "QTY", "UNIT PRICE", "AMOUNT"]]
    for li in data.line_items:
        rows.append([
            Paragraph(li.description, body_st),
            f"{li.quantity:g}",
            _money(sym, li.unit_price),
            _money(sym, li.amount),
        ])
    items_tbl = Table(rows, colWidths=[3.5 * inch, 0.7 * inch, 1.45 * inch,
                                       1.45 * inch], repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, HAIRLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 14))

    tdata = [["Subtotal", _money(sym, totals["subtotal"])]]
    if data.tax_rate_percent > 0:
        tdata.append([f"Tax ({data.tax_rate_percent:g}%)", _money(sym, totals["tax"])])
    tdata.append(["TOTAL", _money(sym, totals["total"])])
    last = len(tdata) - 1
    totals_tbl = Table(tdata, colWidths=[1.75 * inch, 1.65 * inch], hAlign="RIGHT")
    totals_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, last - 1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, last - 1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, last - 1), MUTED),
        ("TEXTCOLOR", (1, 0), (1, last - 1), INK),
        ("BACKGROUND", (0, last), (-1, last), ACCENT),
        ("TEXTCOLOR", (0, last), (-1, last), colors.white),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
        ("FONTSIZE", (0, last), (-1, last), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, last), (-1, last), 9),
        ("BOTTOMPADDING", (0, last), (-1, last), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(totals_tbl)

    if data.notes.strip():
        story.append(Spacer(1, 26))
        story.append(Paragraph("NOTES", label_st))
        story.append(Spacer(1, 3))
        story.append(Paragraph(data.notes.replace("\n", "<br/>"), body_st))

    sig_img = _scaled_image(data.signature_png, max_w=2.2 * inch, max_h=0.85 * inch)
    if sig_img is not None:
        sig_cell = [sig_img, Spacer(1, 2),
                    HRFlowable(width=2.2 * inch, thickness=0.75, color=INK,
                               spaceBefore=2, spaceAfter=4)]
        slabel = data.signature_label.strip() or "Authorised signature"
        sig_cell.append(Paragraph(slabel,
                        style("sig_label", fontName="Helvetica", fontSize=8.5,
                              leading=11, textColor=MUTED, alignment=2)))
        sig_tbl = Table([[sig_cell]], colWidths=[2.4 * inch], hAlign="RIGHT")
        sig_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(Spacer(1, 30))
        story.append(sig_tbl)

    story.append(Spacer(1, 30))
    story.append(HRFlowable(width=content_w, thickness=0.5, color=HAIRLINE,
                            spaceBefore=0, spaceAfter=8))
    story.append(Paragraph("We look forward to working with you.",
                           style("footer", fontName="Helvetica", fontSize=9,
                                 leading=12, textColor=MUTED, alignment=1)))

    doc.build(story)
    return buf.getvalue()


def suggest_filename(data: QuoteData) -> str:
    """Build a filesystem-friendly default filename for the PDF."""
    cust = "".join(c if c.isalnum() else "_" for c in data.customer_name).strip("_") or "customer"
    num = "".join(c if c.isalnum() else "_" for c in data.quote_number).strip("_") or "draft"
    return f"quote_{cust}_{num}.pdf"


def to_record(data: QuoteData, *, status: str = "sent") -> dict:
    """Project ``data`` into the canonical *quote record* dict that the
    quote-recovery pipeline (quote agent → daily plan → approval queue) consumes.
    Pure — no DB."""
    totals = compute_totals(data)
    return {
        "client_name": data.customer_name,
        "quote_number": data.quote_number,
        "quote_amount": totals["total"],
        "quote_date": data.quote_date.isoformat() if data.quote_date else "",
        "quote_status": status,
        "email": data.customer_email,
        "last_follow_up_date": "",
        "follow_up_count": 0,
        "customer_message": "",
    }
