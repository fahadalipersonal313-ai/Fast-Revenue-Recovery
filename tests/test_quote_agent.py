"""Tests for quote follow-up priority and classification."""

from datetime import date, timedelta

from src.quote_agent import analyze_quote, follow_up_priority
from src.models import QuoteClass

REF = date(2026, 6, 14)


def _sent(days_ago: int) -> str:
    return (REF - timedelta(days=days_ago)).isoformat()


def test_follow_up_priority_bands():
    assert follow_up_priority(1) == "soft follow up"
    assert follow_up_priority(5) == "normal follow up"
    assert follow_up_priority(10) == "stronger follow up"
    assert follow_up_priority(30) == "final check in"


def test_won_quote_no_action(settings):
    rec = {"client_name": "X", "quote_number": "Q1", "quote_amount": 1000,
           "quote_date": _sent(5), "quote_status": "Accepted"}
    d = analyze_quote(rec, settings, REF)
    assert d.classification == QuoteClass.WON
    assert d.next_action.lower().startswith("no action")


def test_lost_quote_no_action(settings):
    rec = {"client_name": "Y", "quote_number": "Q2", "quote_amount": 1000,
           "quote_date": _sent(5), "quote_status": "Lost"}
    d = analyze_quote(rec, settings, REF)
    assert d.classification == QuoteClass.LOST


def test_price_objection_detected(settings):
    rec = {"client_name": "Z", "quote_number": "Q3", "quote_amount": 8000,
           "quote_date": _sent(10), "quote_status": "Sent",
           "customer_message": "This is too expensive, any discount?"}
    d = analyze_quote(rec, settings, REF)
    assert d.price_objection is True
    assert d.classification == QuoteClass.REVIEW_REQUIRED


def test_buying_signals_detected(settings):
    rec = {"client_name": "W", "quote_number": "Q4", "quote_amount": 1500,
           "quote_date": _sent(3), "quote_status": "Sent",
           "customer_message": "Ready to proceed, can we book this urgent?"}
    d = analyze_quote(rec, settings, REF)
    assert d.buying_signals
    assert "ready" in d.buying_signals
