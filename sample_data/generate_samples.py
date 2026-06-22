"""Generate realistic, deliberately messy sample spreadsheets.

Run directly (``python sample_data/generate_samples.py``) or import and call
:func:`generate_all`. Dates are relative to today so overdue/aging logic always
has something to react to. The data intentionally includes non-standard column
names, messy phones/emails, missing dates, duplicate names and varied statuses
to exercise the column mapper and the defensive parsing.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
TODAY = date.today()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def d_future(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def build_invoices() -> pd.DataFrame:
    # Note: non-standard headers ("Total Due", "Inv No", "State") on purpose.
    rows = [
        # paid
        ["Acme Corp", "INV-1001", d(40), d(10), 1200.00, "Paid", "", 0, "", "No", "Thanks, paid on time"],
        # 5 days overdue, low risk
        ["Bright Studios", "INV-1002", d(35), d(5), 850.50, "Unpaid", d(8), 1, "", "No", ""],
        # 20 days overdue, medium, 2 reminders
        ["Cedar & Co", "INV-1003", d(50), d(20), 3200.00, "Unpaid", d(7), 2, "", "No", "Will pay soon"],
        # 45 days overdue, high, high value
        ["Delta Logistics", "INV-1004", d(75), d(45), 9800.00, "Overdue", d(15), 3, "", "no", "No reply yet"],
        # 80 days overdue, critical
        ["Echo Retail", "INV-1005", d(120), d(80), 6400.00, "Unpaid", d(20), 4, "", "No", "Customer unreachable"],
        # missed promise
        ["Foxtrot Ltd", "INV-1006", d(60), d(30), 2750.00, "Unpaid", d(10), 2, d(5), "No", "Promised payment last week"],
        # disputed
        ["Acme Corp", "INV-1007", d(40), d(15), 4300.00, "Unpaid", d(6), 1, "", "Yes", "Disputes part of the charge"],
        # not due yet
        ["Golden Gate", "INV-1008", d(2), d_future(20), 1500.00, "Unpaid", "", 0, "", "No", ""],
        # high value above threshold, partial
        ["Helix Health", "INV-1009", d(90), d(55), 15200.00, "Partial", d(12), 2, "", "No", "Paid half"],
        # messy amount + missing due date
        ["Iris Decor", "INV-1010", d(30), "", "$2,450.00", "unpaid", "", 0, "", "no", "Missing due date"],
        # conflicting: marked paid but balance present
        ["Jade Events", "INV-1011", d(33), d(12), 980.00, "Paid", d(5), 1, "", "No", "Says paid but balance shows"],
        # duplicate customer name (Acme Corp again)
        ["Acme Corp", "INV-1012", d(28), d(7), 600.00, "Unpaid", "", 0, "", "No", ""],
    ]
    cols = ["Customer Name", "Inv No", "Invoice Date", "Due Date", "Total Due",
            "Payment Status", "Last Reminder", "Reminders Sent",
            "Promised Date", "Disputed", "Notes"]
    return pd.DataFrame(rows, columns=cols)


def build_quotes() -> pd.DataFrame:
    rows = [
        ["Acme Corp", "Q-2001", 5400.00, d(1), "Sent", "", 0, "Looks good, what's the price breakdown?", ""],
        ["Bright Studios", "Q-2002", 1200.00, d(5), "Sent", d(3), 1, "Can we book this for next week?", ""],
        ["Cedar & Co", "Q-2003", 8800.00, d(12), "Pending", d(9), 2, "It's a bit expensive, any discount?", ""],
        ["Delta Logistics", "Q-2004", 3300.00, d(20), "Sent", d(15), 3, "", "No response in weeks"],
        ["Echo Retail", "Q-2005", 2100.00, d(40), "Sent", d(30), 4, "", "Gone cold"],
        ["Foxtrot Ltd", "Q-2006", 4700.00, d(8), "Accepted", d(2), 1, "Yes let's proceed!", ""],
        ["Golden Gate", "Q-2007", 990.00, d(25), "Lost", d(20), 2, "Went with another vendor", ""],
        ["Helix Health", "Q-2008", 12500.00, d(3), "Sent", "", 0, "Need more details and specs please", ""],
        ["Iris Decor", "Q-2009", "1,750", d(14), "sent", d(10), 2, "Ready to go ahead, urgent", ""],
        ["Jade Events", "Q-2010", 0, "", "Draft", "", 0, "", "Missing date and amount"],
    ]
    cols = ["Client", "Quote #", "Quote Amount", "Quote Date", "Status",
            "Last Follow Up", "Follow Up Count", "Customer Message", "Notes"]
    return pd.DataFrame(rows, columns=cols)


def build_leads() -> pd.DataFrame:
    rows = [
        ["Liam Carter", "Website", "+1 (555) 123-4567", "liam@example.com",
         "Need a quote urgently, ready to book today", "Wedding photography", 5000,
         d(1), d_future(1), "New", "Yes", ""],
        ["Olivia Reed", "Instagram", "555.987.6543", "olivia[at]example.com",
         "How much for a package? Budget is around 2000", "Event catering", 2000,
         d(3), "", "New", "No", "Messy email"],
        ["Noah Brooks", "Referral", "5551112222", "noah@example.com",
         "Just browsing, not sure yet", "Consulting", 0,
         d(10), "", "Contacted", "Yes", ""],
        ["Emma Stone", "Website", "", "emma@example", "This is too expensive for me",
         "Interior design", 800, d(6), "", "Contacted", "No", "Invalid email"],
        ["Ava Mitchell", "Walk-in", "+44 20 7946 0958", "ava@example.co.uk",
         "Can you do it by tomorrow? Deadline is tight", "Printing", 1500,
         d(0), d_future(1), "New", "No", ""],
        ["William Hughes", "Cold call", "555-000-1111", "",
         "Not interested, please remove me", "Insurance", 0,
         d(2), "", "Lost", "No", "Asked to be removed"],
        ["Sophia Turner", "Website", "(555) 222 3333", "sophia@example.com",
         "", "Web design", 0, d(20), "", "Contacted", "No", "No message, gone quiet"],
        ["Liam Carter", "Website", "+1 555 123 4567", "liam@example.com",
         "Following up on my earlier request, still keen", "Wedding photography", 5000,
         d(4), "", "Contacted", "Yes", "Duplicate lead name"],
        ["James Wood", "Facebook", "00 garbage 00", "james@@example..com",
         "Send me more info and pricing please", "Landscaping", 3500,
         "", "", "New", "No", "Messy phone, messy email, missing dates"],
        ["Mia Foster", "Referral", "555 444 5555", "mia@example.com",
         "Booked elsewhere already", "Photography", 0,
         d(15), "", "Dead", "Yes", "Already converted elsewhere"],
    ]
    cols = ["Lead Name", "Source", "Phone", "Email", "Customer Message",
            "Service Requested", "Budget", "Last Contact", "Next Follow Up",
            "Lead Status", "Previous Replies", "Notes"]
    return pd.DataFrame(rows, columns=cols)


def build_bulk_invoices() -> pd.DataFrame:
    # Note: non-standard headers ("Bill To", "Inv #", "Net Due") on purpose, to
    # exercise the invoice_bulk column mapper/auto-detect just like the others.
    rows = [
        ["Acme Corp", "Acme Corporation Ltd", "Priya Shah", "priya@acme.example",
         "+1 (555) 010-2020", "12 Market St, Springfield", "BLK-3001", 1450.00,
         d(2), d_future(28), "Website redesign — phase 1"],
        ["Bright Studios", "Bright Studios LLC", "Tom Walsh", "tom@brightstudios.example",
         "555.010.3030", "88 Loft Ave, Riverside", "BLK-3002", 620.00,
         d(0), d_future(14), "Headshot photography session"],
        ["", "Cedar & Co", "Maria Lopez", "billing@cedarco.example",
         "+1-555-010-4040", "200 Pine Rd, Lakeview", "BLK-3003", 3980.00,
         d(1), d_future(30), "Quarterly bookkeeping retainer"],
        ["Delta Logistics", "", "", "ap@delta-logistics.example",
         "", "9 Harbor Way, Port City", "BLK-3004", "$2,150.00",
         d(3), d_future(21), "Freight consulting — March"],
        ["Echo Retail", "Echo Retail Group", "Jamie Fox", "jamie[at]echoretail.example",
         "555 010 5050", "", "BLK-3005", 875.50,
         "", d_future(7), "POS system setup"],
    ]
    cols = ["Customer Name", "Bill To", "Contact Person", "Email", "Mobile",
            "Address", "Inv #", "Net Due", "Invoice Date", "Due Date",
            "Description"]
    return pd.DataFrame(rows, columns=cols)


def generate_all(out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "invoices": out_dir / "sample_invoices.xlsx",
        "quotes": out_dir / "sample_quotes.xlsx",
        "leads": out_dir / "sample_leads.xlsx",
        "bulk_invoices": out_dir / "sample_bulk_invoices.xlsx",
    }
    build_invoices().to_excel(paths["invoices"], index=False)
    build_quotes().to_excel(paths["quotes"], index=False)
    build_leads().to_excel(paths["leads"], index=False)
    build_bulk_invoices().to_excel(paths["bulk_invoices"], index=False)
    return paths


if __name__ == "__main__":
    created = generate_all()
    for kind, p in created.items():
        print(f"Wrote {kind}: {p}")
