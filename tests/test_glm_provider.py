"""Tests for the GLM (Z.ai) provider — config wiring + the fail-safe REST
backend. No real network: ``requests.post`` is stubbed. We verify provider
selection, model/key resolution, response parsing, and that every failure mode
(no key, non-200, network error, junk payload) falls back to None."""

from __future__ import annotations

import types

import src.ai_helper as ai
from src.config import Settings


# --- config wiring ---------------------------------------------------------
def test_glm_default_model_and_key(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("GLM_API_KEY", "glm-secret")
    s = Settings(ai_enabled=True, ai_provider="glm")
    assert s.ai_model_resolved == "glm-4.5-flash"
    assert s.ai_api_key == "glm-secret"
    assert s.ai_active is True


def test_glm_ignores_model_from_other_provider(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    # A leftover gemini/claude id must not be sent to the GLM endpoint.
    assert Settings(ai_provider="glm", ai_model="gemini-2.5-flash-lite").ai_model_resolved \
        == "glm-4.5-flash"
    assert Settings(ai_provider="glm", ai_model="claude-opus-4-8").ai_model_resolved \
        == "glm-4.5-flash"
    # An explicit glm id is honoured.
    assert Settings(ai_provider="glm", ai_model="glm-4.7-flash").ai_model_resolved \
        == "glm-4.7-flash"


def test_glm_available_only_with_key(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    assert ai.ai_available(Settings(ai_enabled=True, ai_provider="glm")) is False
    monkeypatch.setenv("GLM_API_KEY", "k")
    assert ai.ai_available(Settings(ai_enabled=True, ai_provider="glm")) is True


# --- REST backend ----------------------------------------------------------
def _fake_post(status=200, payload=None, boom=False):
    def post(url, headers=None, json=None, timeout=None):
        if boom:
            raise RuntimeError("network down")
        return types.SimpleNamespace(status_code=status, json=lambda: payload)
    return post


def _glm_settings(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    return Settings(ai_enabled=True, ai_provider="glm")


def test_glm_complete_parses_content(monkeypatch):
    payload = {"choices": [{"message": {"content": "  Polished text.  "}}]}
    monkeypatch.setattr("requests.post", _fake_post(payload=payload))
    out = ai._glm_complete("sys", "prompt", _glm_settings(monkeypatch), 100)
    assert out == "Polished text."


def test_glm_complete_routes_through_complete(monkeypatch):
    payload = {"choices": [{"message": {"content": "ok"}}]}
    monkeypatch.setattr("requests.post", _fake_post(payload=payload))
    assert ai._complete("s", "p", _glm_settings(monkeypatch), 50) == "ok"


def test_glm_complete_fails_safe_on_non_200(monkeypatch):
    monkeypatch.setattr("requests.post", _fake_post(status=429, payload={}))
    assert ai._glm_complete("s", "p", _glm_settings(monkeypatch), 50) is None


def test_glm_complete_fails_safe_on_network_error(monkeypatch):
    monkeypatch.setattr("requests.post", _fake_post(boom=True))
    assert ai._glm_complete("s", "p", _glm_settings(monkeypatch), 50) is None


def test_glm_complete_fails_safe_on_junk_payload(monkeypatch):
    monkeypatch.setattr("requests.post", _fake_post(payload={"unexpected": 1}))
    assert ai._glm_complete("s", "p", _glm_settings(monkeypatch), 50) is None


def test_glm_complete_none_without_key(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    s = Settings(ai_enabled=True, ai_provider="glm")
    assert ai._glm_complete("s", "p", s, 50) is None
