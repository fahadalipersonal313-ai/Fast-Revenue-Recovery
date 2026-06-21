"""Unit tests for src.analytics — the metrics layer.

Uses the standard ``memory`` fixture (fresh per-tenant SQLite in tmp_path) and
seeds records via ``mem.save_record`` so the tests exercise the same write
path the app uses.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src import analytics
from src import database as db


REF = date(2026, 6, 14)


def _seed_invoice(
    mem,
    *,
    ref: str,
    amount: float,
    status: str,
    due_offset_days: int | None = 0,
    customer: str = "Acme",
):
    """Save an invoice with a due_date relative to REF (or None)."""
    payload = {
        "customer_name": customer,
        "invoice_number": ref,
        "amount_due": amount,
        "payment_status": status,
    }
    if due_offset_days is not None:
        payload["due_date"] = (REF + timedelta(days=due_offset_days)).isoformat()
    outcome = "recovered" if status.lower() in {"paid", "settled"} else "open"
    mem.save_record("invoice", ref, customer, amount, status, payload, outcome)


def _seed_quote(mem, *, ref, amount, status, customer="Acme"):
    mem.save_record(
        "quote", ref, customer, amount, status,
        {"client_name": customer, "quote_number": ref, "amount": amount,
         "quote_status": status},
        "won" if status.lower() in analytics.QUOTE_WON_STATUSES else "open",
    )


def _seed_lead(mem, *, ref, amount, status, customer="Acme"):
    mem.save_record(
        "lead", ref, customer, amount, status,
        {"lead_name": customer, "lead_id": ref, "amount": amount,
         "lead_status": status},
        "converted" if status.lower() in analytics.LEAD_CONVERTED_STATUSES else "open",
    )


# ---------------------------------------------------------------------------
# stats()
# ---------------------------------------------------------------------------
class TestStats:
    def test_empty_db_returns_zero_shape_with_has_data_false(self, memory):
        s = analytics.stats(memory)
        assert s["has_data"] is False
        for key in ("recovered", "at_risk", "total_invoice", "quote_value",
                    "lead_value", "won", "converted", "pending", "handled",
                    "total_items", "open_tasks", "overdue_tasks", "due_today"):
            assert s[key] == 0, f"{key} should be zero when DB is empty"

    def test_recovered_and_at_risk_split_invoices_by_status(self, memory):
        _seed_invoice(memory, ref="INV-1", amount=1000, status="paid")
        _seed_invoice(memory, ref="INV-2", amount=2500, status="unpaid")
        _seed_invoice(memory, ref="INV-3", amount=500,  status="Settled")  # case-insensitive
        s = analytics.stats(memory)
        assert s["recovered"] == 1500   # 1000 + 500
        assert s["at_risk"] == 2500
        assert s["total_invoice"] == 4000
        assert s["has_data"] is True

    def test_open_quotes_count_toward_at_risk(self, memory):
        _seed_invoice(memory, ref="INV-1", amount=1000, status="unpaid")
        _seed_quote(memory, ref="Q-1", amount=300, status="sent")
        s = analytics.stats(memory)
        assert s["at_risk"] == 1300
        assert s["quote_value"] == 300

    def test_won_quotes_and_converted_leads_counted(self, memory):
        _seed_quote(memory, ref="Q-1", amount=100, status="won")
        _seed_quote(memory, ref="Q-2", amount=200, status="Accepted")
        _seed_quote(memory, ref="Q-3", amount=50,  status="sent")
        _seed_lead(memory, ref="L-1", amount=0, status="converted")
        _seed_lead(memory, ref="L-2", amount=0, status="new")
        s = analytics.stats(memory)
        assert s["won"] == 2
        assert s["converted"] == 1
        assert s["lead_value"] == 0

    def test_stats_handles_null_status(self, memory):
        # Status NULL must not crash _norm_status nor explode sums.
        memory.save_record("invoice", "INV-X", "Acme", 100.0, None,
                           {"customer_name": "Acme", "invoice_number": "INV-X"},
                           "open")
        s = analytics.stats(memory)
        assert s["at_risk"] == 100.0
        assert s["recovered"] == 0


# ---------------------------------------------------------------------------
# aging_buckets()
# ---------------------------------------------------------------------------
class TestAgingBuckets:
    def test_returns_every_bucket_even_when_empty(self, memory):
        buckets = analytics.aging_buckets(memory, on_date=REF)
        labels = [b["label"] for b in buckets]
        assert labels == ["Not yet due", "1–30 days", "31–60 days",
                          "61–90 days", "90+ days"]
        assert all(b["count"] == 0 and b["amount"] == 0 for b in buckets)

    def test_distributes_invoices_into_correct_buckets(self, memory):
        # Five unpaid invoices, one per bucket.
        _seed_invoice(memory, ref="A", amount=100, status="unpaid", due_offset_days=+5)   # not yet due
        _seed_invoice(memory, ref="B", amount=200, status="unpaid", due_offset_days=-15)  # 1–30
        _seed_invoice(memory, ref="C", amount=400, status="unpaid", due_offset_days=-45)  # 31–60
        _seed_invoice(memory, ref="D", amount=800, status="unpaid", due_offset_days=-75)  # 61–90
        _seed_invoice(memory, ref="E", amount=1600, status="unpaid", due_offset_days=-180) # 90+
        buckets = {b["label"]: b for b in analytics.aging_buckets(memory, on_date=REF)}
        assert buckets["Not yet due"]["count"] == 1 and buckets["Not yet due"]["amount"] == 100
        assert buckets["1–30 days"]["count"] == 1 and buckets["1–30 days"]["amount"] == 200
        assert buckets["31–60 days"]["count"] == 1 and buckets["31–60 days"]["amount"] == 400
        assert buckets["61–90 days"]["count"] == 1 and buckets["61–90 days"]["amount"] == 800
        assert buckets["90+ days"]["count"] == 1 and buckets["90+ days"]["amount"] == 1600

    def test_bucket_edges_are_inclusive(self, memory):
        # Exactly at 30 days overdue → 1–30; at 31 → 31–60; at 0 (due today) → Not yet due.
        _seed_invoice(memory, ref="EDGE0",  amount=10, status="unpaid", due_offset_days=0,   customer="C0")
        _seed_invoice(memory, ref="EDGE30", amount=20, status="unpaid", due_offset_days=-30, customer="C30")
        _seed_invoice(memory, ref="EDGE31", amount=40, status="unpaid", due_offset_days=-31, customer="C31")
        buckets = {b["label"]: b for b in analytics.aging_buckets(memory, on_date=REF)}
        assert buckets["Not yet due"]["count"] == 1
        assert buckets["1–30 days"]["count"] == 1 and buckets["1–30 days"]["amount"] == 20
        assert buckets["31–60 days"]["count"] == 1 and buckets["31–60 days"]["amount"] == 40

    def test_skips_paid_invoices(self, memory):
        _seed_invoice(memory, ref="PAID", amount=999, status="paid", due_offset_days=-50)
        _seed_invoice(memory, ref="OPEN", amount=100, status="unpaid", due_offset_days=-50)
        buckets = {b["label"]: b for b in analytics.aging_buckets(memory, on_date=REF)}
        assert buckets["31–60 days"]["count"] == 1
        assert buckets["31–60 days"]["amount"] == 100

    def test_skips_invoices_without_due_date(self, memory):
        _seed_invoice(memory, ref="NODATE", amount=500, status="unpaid", due_offset_days=None)
        buckets = analytics.aging_buckets(memory, on_date=REF)
        assert all(b["count"] == 0 for b in buckets)


# ---------------------------------------------------------------------------
# status_breakdown()
# ---------------------------------------------------------------------------
class TestStatusBreakdown:
    def test_empty_returns_empty_list(self, memory):
        assert analytics.status_breakdown(memory, "invoice") == []

    def test_groups_and_normalises_statuses(self, memory):
        _seed_invoice(memory, ref="A", amount=100, status="Paid",  customer="X")
        _seed_invoice(memory, ref="B", amount=200, status="paid",  customer="Y")
        _seed_invoice(memory, ref="C", amount=50,  status="UNPAID", customer="Z")
        rows = analytics.status_breakdown(memory, "invoice")
        as_dict = {r["status"]: r for r in rows}
        assert as_dict["paid"]["count"] == 2 and as_dict["paid"]["amount"] == 300
        assert as_dict["unpaid"]["count"] == 1 and as_dict["unpaid"]["amount"] == 50

    def test_sorted_by_amount_desc(self, memory):
        _seed_invoice(memory, ref="A", amount=100, status="small", customer="X")
        _seed_invoice(memory, ref="B", amount=9000, status="big", customer="Y")
        _seed_invoice(memory, ref="C", amount=500, status="medium", customer="Z")
        rows = analytics.status_breakdown(memory, "invoice")
        assert [r["status"] for r in rows] == ["big", "medium", "small"]

    def test_missing_status_collapses_to_unknown(self, memory):
        memory.save_record("invoice", "X", "Acme", 100, None, {"customer_name": "Acme"}, "open")
        memory.save_record("invoice", "Y", "Acme", 50, "", {"customer_name": "Acme"}, "open")
        rows = analytics.status_breakdown(memory, "invoice")
        assert len(rows) == 1 and rows[0]["status"] == "unknown"
        assert rows[0]["count"] == 2 and rows[0]["amount"] == 150

    def test_filters_by_record_type(self, memory):
        _seed_invoice(memory, ref="I", amount=100, status="paid")
        _seed_quote(memory, ref="Q", amount=200, status="sent")
        inv = analytics.status_breakdown(memory, "invoice")
        quo = analytics.status_breakdown(memory, "quote")
        assert {r["status"] for r in inv} == {"paid"}
        assert {r["status"] for r in quo} == {"sent"}


# ---------------------------------------------------------------------------
# recovery_rate_over_time()
# ---------------------------------------------------------------------------
def _set_created_at(memory, ref: str, when: str) -> None:
    """Override the auto-set created_at so we can simulate older cohorts."""
    db.execute("UPDATE records SET created_at=? WHERE reference=?",
               (when, ref), path=memory.path)


class TestRecoveryRateOverTime:
    def test_returns_requested_number_of_periods(self, memory):
        series = analytics.recovery_rate_over_time(
            memory, period="month", periods=4, on_date=REF
        )
        assert len(series) == 4
        assert series[-1]["period"] == "2026-06"  # ends at on_date's period
        assert series[0]["period"] == "2026-03"   # oldest first

    def test_empty_db_gives_all_zero_rates(self, memory):
        series = analytics.recovery_rate_over_time(
            memory, period="month", periods=3, on_date=REF
        )
        assert all(s["recovered"] == 0 and s["outstanding"] == 0
                   and s["rate"] == 0.0 for s in series)

    def test_rate_per_cohort(self, memory):
        # June cohort: 800 paid out of 1000 → 0.8.
        # May cohort:  0 paid out of 500 → 0.0.
        _seed_invoice(memory, ref="J1", amount=800, status="paid",   customer="J1")
        _seed_invoice(memory, ref="J2", amount=200, status="unpaid", customer="J2")
        _seed_invoice(memory, ref="M1", amount=500, status="unpaid", customer="M1")
        _set_created_at(memory, "J1", "2026-06-05 10:00:00")
        _set_created_at(memory, "J2", "2026-06-10 10:00:00")
        _set_created_at(memory, "M1", "2026-05-20 10:00:00")

        series = analytics.recovery_rate_over_time(
            memory, period="month", periods=3, on_date=REF
        )
        by_period = {s["period"]: s for s in series}
        assert by_period["2026-06"]["recovered"] == 800
        assert by_period["2026-06"]["outstanding"] == 200
        assert by_period["2026-06"]["rate"] == pytest.approx(0.8)
        assert by_period["2026-05"]["recovered"] == 0
        assert by_period["2026-05"]["outstanding"] == 500
        assert by_period["2026-05"]["rate"] == 0.0
        # April had nothing → zeros, not omitted.
        assert by_period["2026-04"]["rate"] == 0.0

    def test_weekly_period_labels(self, memory):
        series = analytics.recovery_rate_over_time(
            memory, period="week", periods=3, on_date=REF
        )
        assert len(series) == 3
        # %Y-%W where Sunday-starts-week=0; sanity check format only.
        assert all(len(s["period"]) == 7 and s["period"][4] == "-" for s in series)

    def test_rejects_unknown_period(self, memory):
        with pytest.raises(ValueError, match="unknown period"):
            analytics.recovery_rate_over_time(memory, period="day")

    def test_rejects_non_positive_periods(self, memory):
        with pytest.raises(ValueError, match="periods must be >= 1"):
            analytics.recovery_rate_over_time(memory, periods=0)

    def test_ignores_non_invoice_records(self, memory):
        # Quotes and leads must not pollute the invoice cohort series.
        _seed_quote(memory, ref="Q1", amount=9999, status="sent")
        _seed_lead(memory, ref="L1", amount=9999, status="new")
        series = analytics.recovery_rate_over_time(
            memory, period="month", periods=2, on_date=REF
        )
        assert all(s["outstanding"] == 0 and s["recovered"] == 0 for s in series)
