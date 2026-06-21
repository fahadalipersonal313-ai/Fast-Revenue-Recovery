"""Excel export generation.

Each builder returns a pandas DataFrame; ``to_excel_bytes`` renders one or more
frames into a downloadable .xlsx using openpyxl. Streamlit download buttons consume
the bytes directly, and ``save_to_exports`` can also drop a file on disk.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from . import database as db
from .config import EXPORTS_DIR
from .memory import AgentMemory
from .models import SupervisorDecision


def to_excel_bytes(frames: Dict[str, pd.DataFrame]) -> bytes:
    """Render {sheet_name: dataframe} to an .xlsx byte string."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if not frames:
            pd.DataFrame({"info": ["No data"]}).to_excel(
                writer, sheet_name="Empty", index=False
            )
        for name, frame in frames.items():
            safe = (frame if frame is not None else pd.DataFrame())
            # Excel sheet names max 31 chars and forbid some characters.
            sheet = name[:31].replace("/", "-").replace("\\", "-")
            safe.to_excel(writer, sheet_name=sheet or "Sheet1", index=False)
    return buffer.getvalue()


def save_to_exports(filename: str, data: bytes) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = EXPORTS_DIR / f"{Path(filename).stem}_{stamp}.xlsx"
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Report builders (DataFrames)
# ---------------------------------------------------------------------------
def daily_plan_frame(plan: List[SupervisorDecision]) -> pd.DataFrame:
    rows = []
    for rank, sd in enumerate(plan, start=1):
        rows.append(
            {
                "Rank": rank,
                "Type": sd.record_type.value,
                "Customer": sd.name,
                "Reference": sd.reference,
                "Amount/Value": sd.amount,
                "Priority": sd.priority.value,
                "Score": sd.priority_score,
                "Reason": sd.reason,
                "Recommended action": sd.recommended_action,
                "Suggested message": sd.suggested_message,
                "Approval required": "Yes" if sd.requires_approval else "No",
                "Next follow-up": (
                    sd.next_follow_up_date.isoformat() if sd.next_follow_up_date else ""
                ),
                "Blocked actions": ", ".join(sd.blocked_actions),
            }
        )
    return pd.DataFrame(rows)


def _table_frame(memory: AgentMemory, table: str) -> pd.DataFrame:
    rows = db.query(f"SELECT * FROM {table} ORDER BY id DESC", path=memory.path)
    return pd.DataFrame(rows)


def approvals_frame(memory: AgentMemory) -> pd.DataFrame:
    return _table_frame(memory, "approvals")


def messages_frame(memory: AgentMemory) -> pd.DataFrame:
    return _table_frame(memory, "messages")


def recommendations_frame(memory: AgentMemory) -> pd.DataFrame:
    return _table_frame(memory, "recommendations")


def decision_log_frame(memory: AgentMemory) -> pd.DataFrame:
    return _table_frame(memory, "decision_log")


def records_frame(memory: AgentMemory, record_type: str) -> pd.DataFrame:
    rows = db.query(
        "SELECT record_type, reference, customer_name, amount, status, outcome, created_at "
        "FROM records WHERE record_type=? ORDER BY id DESC",
        (record_type,),
        path=memory.path,
    )
    return pd.DataFrame(rows)


def customer_history_frame(memory: AgentMemory, customer: str) -> Dict[str, pd.DataFrame]:
    hist = memory.customer_history(customer)
    return {k: pd.DataFrame(v) for k, v in hist.items()}


def combined_report(memory: AgentMemory) -> bytes:
    """A single workbook with every key table on its own sheet."""
    frames = {
        "Approvals": approvals_frame(memory),
        "Messages": messages_frame(memory),
        "Recommendations": recommendations_frame(memory),
        "Invoices": records_frame(memory, "invoice"),
        "Quotes": records_frame(memory, "quote"),
        "Leads": records_frame(memory, "lead"),
        "Decision log": decision_log_frame(memory),
    }
    return to_excel_bytes(frames)
