"""Populate the app database with the three sample files — handy for a demo.

Usage (from the project folder, with the venv active):

    python seed_demo.py

Then run `streamlit run app.py` and the dashboard will be full of example data.
This only adds data; it never sends anything.
"""

from __future__ import annotations

import pandas as pd

from sample_data.generate_samples import generate_all
from src import column_mapper as cm
from src.approval_engine import analyze_and_queue, queue_counts
from src.config import SAMPLE_DIR
from src.memory import AgentMemory


def run() -> None:
    generate_all()
    mem = AgentMemory()
    settings = mem.load_settings()
    files = {
        "invoice": "sample_invoices.xlsx",
        "quote": "sample_quotes.xlsx",
        "lead": "sample_leads.xlsx",
    }
    for record_type, filename in files.items():
        df = pd.read_excel(SAMPLE_DIR / filename)
        mapping, _ = cm.detect_mapping(list(df.columns), record_type)
        processed = cm.apply_mapping(df, mapping)
        records = [
            {k: (None if pd.isna(v) else v) for k, v in row.items()}
            for row in processed.to_dict("records")
        ]
        analyze_and_queue(mem, settings, {record_type: records})
    print("Demo data loaded. Approval queue:", queue_counts(mem))
    print("Now run:  streamlit run app.py")


if __name__ == "__main__":
    run()
