"""Robust ingestion of messy client files.

Real client files are not clean: different encodings, ``;`` or tab delimiters,
a few junk/title rows above the real header, and Excel workbooks with several
sheets. This module turns any of those into a tidy DataFrame, and reports what
it found so the UI can let the user override (pick a sheet, set the header row).

It deliberately does *not* know anything about invoices/quotes/leads — that is
the column mapper's job. This layer only produces a clean table.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_DELIMS = [",", ";", "\t", "|"]


def is_excel(filename: str) -> bool:
    return filename.lower().rsplit(".", 1)[-1] in {"xlsx", "xls", "xlsm"}


def _decode(data: bytes) -> Tuple[str, str]:
    """Return (text, encoding) trying a few common encodings."""
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace"), "utf-8 (lossy)"


def _sniff_delimiter(text: str) -> str:
    """Pick the delimiter that appears most consistently across sample lines.

    More reliable than ``csv.Sniffer`` on real files, where a stray comma inside
    a number (``1.200,50``) or title rows above the table easily mislead it.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for delim in _DELIMS:
        counts = [ln.count(delim) for ln in lines]
        nonzero = [c for c in counts if c > 0]
        if not nonzero:
            continue
        # Modal field-separator count, rewarded for repeating across lines.
        modal = max(set(nonzero), key=nonzero.count)
        score = nonzero.count(modal) * modal
        if score > best_score:
            best_score, best = score, delim
    return best


def _csv_to_grid(text: str, delim: str) -> pd.DataFrame:
    """Parse CSV text into a ragged-safe DataFrame (no header inference).

    Uses ``csv.reader`` so quoted fields and rows of differing widths — common
    when there are title rows above the table — are preserved, not skipped.
    """
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)
            if any((c or "").strip() for c in r)]
    if not rows:
        return pd.DataFrame()
    width = max(len(r) for r in rows)
    padded = [r + [None] * (width - len(r)) for r in rows]
    return pd.DataFrame(padded, dtype=object)


def excel_sheets(data: bytes) -> List[str]:
    try:
        return pd.ExcelFile(io.BytesIO(data)).sheet_names
    except Exception:  # noqa: BLE001
        return []


def _looks_like_header(values: List[Any]) -> int:
    """Score a row on how 'header-like' it is (more = better)."""
    score = 0
    seen = set()
    for v in values:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        text = str(v).strip()
        if not text:
            continue
        # Headers are usually short-ish text, not pure numbers.
        is_number = text.replace(".", "", 1).replace("-", "", 1).isdigit()
        if not is_number and len(text) <= 40:
            score += 2
        else:
            score += 1
        if text.lower() not in seen:
            seen.add(text.lower())
            score += 1  # reward uniqueness
    return score


def detect_header_row(raw: pd.DataFrame, max_scan: int = 12) -> int:
    """Pick the most likely header row among the first ``max_scan`` rows."""
    best_row, best_score = 0, -1
    for i in range(min(max_scan, len(raw))):
        score = _looks_like_header(list(raw.iloc[i].values))
        if score > best_score:
            best_score, best_row = score, i
    return best_row


def _finalise(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    header_row = max(0, min(header_row, len(raw) - 1)) if len(raw) else 0
    headers = []
    seen: Dict[str, int] = {}
    for j, val in enumerate(raw.iloc[header_row].tolist()):
        name = "" if val is None or (isinstance(val, float) and pd.isna(val)) else str(val).strip()
        if not name:
            name = f"column_{j + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)
    body = raw.iloc[header_row + 1:].copy()
    body.columns = headers
    # Drop fully empty rows and columns.
    body = body.dropna(axis=0, how="all").dropna(axis=1, how="all")
    body = body.reset_index(drop=True)
    return body


def inspect(data: bytes, filename: str) -> Dict[str, Any]:
    """Quick look at a file so the UI can offer sheet/encoding/delimiter options."""
    if is_excel(filename):
        return {"kind": "excel", "sheets": excel_sheets(data)}
    text, enc = _decode(data)
    return {"kind": "csv", "encoding": enc, "delimiter": _sniff_delimiter(text)}


def read_table(
    data: bytes,
    filename: str,
    sheet: Optional[str] = None,
    header_row: Optional[int] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Read any supported file into a clean DataFrame.

    ``header_row=None`` triggers auto-detection. Returns (dataframe, meta) where
    meta records the choices made (sheet, header_row, delimiter, encoding).
    """
    meta: Dict[str, Any] = {"filename": filename}

    if is_excel(filename):
        xls = pd.ExcelFile(io.BytesIO(data))
        meta["sheets"] = xls.sheet_names
        use_sheet = sheet if sheet in xls.sheet_names else xls.sheet_names[0]
        meta["sheet"] = use_sheet
        raw = xls.parse(sheet_name=use_sheet, header=None, dtype=object)
    else:
        text, enc = _decode(data)
        delim = _sniff_delimiter(text)
        meta["encoding"], meta["delimiter"] = enc, delim
        raw = _csv_to_grid(text, delim)

    if raw.empty:
        return pd.DataFrame(), {**meta, "header_row": 0, "rows": 0}

    hr = detect_header_row(raw) if header_row is None else header_row
    meta["header_row"] = hr
    df = _finalise(raw, hr)
    meta["rows"] = len(df)
    return df, meta
