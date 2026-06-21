"""Tests for lead scoring, temperature and stop rules."""

from datetime import date, timedelta

from src.lead_agent import analyze_lead, temperature_for
from src.models import LeadTemperature

REF = date(2026, 6, 14)


def test_temperature_bands():
    assert temperature_for(80, False) == LeadTemperature.HOT
    assert temperature_for(50, False) == LeadTemperature.WARM
    assert temperature_for(20, False) == LeadTemperature.COLD
    assert temperature_for(5, False) == LeadTemperature.DEAD
    assert temperature_for(90, True) == LeadTemperature.DEAD  # lost overrides


def test_hot_lead_scoring(settings):
    rec = {"lead_name": "Liam", "customer_message": "Need a quote urgently, ready to book today",
           "budget": 5000, "last_contact_date": REF.isoformat(), "lead_status": "New",
           "previous_replies": "yes"}
    d = analyze_lead(rec, settings, REF)
    assert d.lead_score >= 70
    assert d.temperature == LeadTemperature.HOT
    assert d.score_explanation  # must explain why


def test_lost_lead_stops(settings):
    rec = {"lead_name": "Will", "customer_message": "Not interested",
           "budget": 0, "last_contact_date": (REF - timedelta(days=2)).isoformat(),
           "lead_status": "Lost"}
    d = analyze_lead(rec, settings, REF)
    assert d.stop_follow_ups is True
    assert d.temperature == LeadTemperature.DEAD
    assert not d.messages


def test_cold_lead(settings):
    rec = {"lead_name": "Sophia", "customer_message": "", "budget": 0,
           "last_contact_date": (REF - timedelta(days=20)).isoformat(),
           "lead_status": "Contacted"}
    d = analyze_lead(rec, settings, REF)
    assert d.temperature in (LeadTemperature.COLD, LeadTemperature.DEAD)
