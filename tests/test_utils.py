"""Tests for date and amount calculations."""

from datetime import date

from src.utils import (
    clean_email,
    clean_phone,
    days_overdue,
    looks_disputed,
    parse_amount,
    parse_date,
)


def test_days_overdue_basic():
    ref = date(2026, 6, 14)
    assert days_overdue(date(2026, 6, 4), ref) == 10
    assert days_overdue(date(2026, 6, 20), ref) == 0  # not yet due
    assert days_overdue(None, ref) == 0  # unknown due date


def test_parse_date_multiple_formats():
    assert parse_date("2026-06-14") == date(2026, 6, 14)
    assert parse_date("14/06/2026") == date(2026, 6, 14)
    assert parse_date("June 14, 2026") == date(2026, 6, 14)
    assert parse_date("") is None
    assert parse_date("not a date") is None


def test_parse_amount_messy():
    assert parse_amount("$1,250.50") == 1250.50
    assert parse_amount("2.450,00") == 2450.00  # european style
    assert parse_amount("1750") == 1750.0
    assert parse_amount("") == 0.0
    assert parse_amount("free text") == 0.0


def test_clean_contacts():
    assert clean_phone("+1 (555) 123-4567") == "+15551234567"
    assert clean_phone("garbage") == ""
    assert clean_email("Liam@Example.com ") == "liam@example.com"
    assert clean_email("olivia[at]example.com") == ""


def test_looks_disputed():
    assert looks_disputed("Yes") is True
    assert looks_disputed("disputed") is True
    assert looks_disputed("No", "unpaid") is False
