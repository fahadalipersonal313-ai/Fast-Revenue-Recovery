"""Optional AI assistance — strictly non-essential and fail-safe.

Design rules enforced here:

* The whole app must work with AI disabled or unavailable.
* AI may only *interpret text* and *polish wording*. It never computes money,
  dates, risk, or approval decisions — those are Python's job.
* Any failure (no key, no library, network error) returns ``None`` so callers
  fall back to deterministic templates/rules.

Two providers are supported, selected by ``settings.ai_provider``:

* ``gemini`` (default) — Google's Gemini API, which has a generous free tier
  (Gemini 2.0 Flash), so the app can ship with AI polishing on at $0 cost.
* ``anthropic`` — Claude, for users who already have an API key.

Both providers implement the exact same two functions below, so the rest of
the app (``communication_agent.py``) never needs to know which one is active.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from .config import Settings

_REFINE_SYSTEM_PROMPT = (
    "You refine debt-collection and sales follow-up messages for a small "
    "business. Keep it polite, professional, warm and concise. NEVER add "
    "threats, legal language, late fees, or any new numbers, amounts, dates "
    "or promises that are not already present. NEVER insert placeholders or "
    "bracketed fill-ins like [Date] or [Name]; if a detail is not in the "
    "original message, leave it out entirely. Return only the improved "
    "message text, nothing else."
)

_SUMMARY_SYSTEM_PROMPT = (
    "Summarise the customer's message in one short, neutral sentence. "
    "Do not invent facts."
)


def ai_available(settings: Settings) -> bool:
    """True only if AI is enabled, a key exists, and the SDK imports."""
    if not settings.ai_active:
        return False
    if settings.ai_provider == "gemini":
        try:
            from google import genai  # noqa: F401
        except Exception:
            return False
        return True
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------
def _anthropic_client(settings: Settings):
    try:
        import anthropic
    except Exception:
        return None
    try:
        return anthropic.Anthropic(api_key=settings.ai_api_key)
    except Exception:
        return None


def _anthropic_complete(system: str, prompt: str, settings: Settings, max_tokens: int) -> Optional[str]:
    client = _anthropic_client(settings)
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=settings.ai_model_resolved,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts).strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gemini backend (free tier, via the google-genai SDK)
# ---------------------------------------------------------------------------
def _gemini_client(settings: Settings):
    try:
        from google import genai
    except Exception:
        return None
    try:
        return genai.Client(api_key=settings.ai_api_key)
    except Exception:
        return None


def _gemini_complete(system: str, prompt: str, settings: Settings, max_tokens: int) -> Optional[str]:
    client = _gemini_client(settings)
    if client is None:
        return None
    try:
        from google.genai import types

        config_kwargs = dict(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.4,
        )
        # Gemini 2.5 models "think" by default, and those hidden reasoning tokens
        # count against max_output_tokens — which truncates a short message. We
        # do not need reasoning to polish wording, so switch thinking off when
        # the SDK supports it (older SDKs/models simply ignore this).
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass

        resp = client.models.generate_content(
            model=settings.ai_model_resolved,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = (getattr(resp, "text", "") or "").strip()
        return text or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public, provider-agnostic API
# ---------------------------------------------------------------------------
def _complete(system: str, prompt: str, settings: Settings, max_tokens: int) -> Optional[str]:
    if settings.ai_provider == "gemini":
        return _gemini_complete(system, prompt, settings, max_tokens)
    return _anthropic_complete(system, prompt, settings, max_tokens)


def improve_message(text: str, tone_hint: str, settings: Settings) -> Optional[str]:
    """Return a polished version of ``text`` or None to keep the original.

    Never invents amounts, dates or commitments — the prompt forbids it and the
    caller still owns the deterministic content.
    """
    if not ai_available(settings) or not text.strip():
        return None
    prompt = f"Tone: {tone_hint}\n\nMessage to refine:\n{text}"
    return _complete(_REFINE_SYSTEM_PROMPT, prompt, settings, max_tokens=600)


def summarize_context(text: str, settings: Settings) -> Optional[str]:
    """One-line summary of a customer message; None on any failure."""
    if not ai_available(settings) or not text.strip():
        return None
    return _complete(_SUMMARY_SYSTEM_PROMPT, text, settings, max_tokens=120)


# ---------------------------------------------------------------------------
# Tone variants — generate gentle / neutral / firm rewrites to choose from
# ---------------------------------------------------------------------------
# Canonical tones offered. Kept here so the UI and the prompt agree.
TONE_VARIANTS: List[str] = ["gentle", "neutral", "firm"]

_VARIANTS_SYSTEM_PROMPT = (
    "You rewrite a debt-collection or sales follow-up message for a small "
    "business in three different tones: gentle, neutral, and firm. Rules for "
    "EVERY version: stay polite and professional; keep all the facts identical; "
    "NEVER add threats, legal language, late fees, or any new numbers, amounts, "
    "dates or promises that are not already present; NEVER insert placeholders "
    "or bracketed fill-ins. 'firm' means clear and direct, never aggressive. "
    "Respond with ONLY a JSON object of the form "
    '{"gentle": "...", "neutral": "...", "firm": "..."} and nothing else.'
)


def _extract_json(raw: str) -> Optional[dict]:
    """Best-effort: pull the first JSON object out of a model response."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


_CUSTOM_FIELDS_SYSTEM_PROMPT = (
    "You tidy up user-entered extra fields for a business invoice or quotation. "
    "For each field you are given a label and a value. Return the SAME fields in "
    "the SAME order, lightly cleaned for a professional document: fix casing and "
    "spacing on the label (e.g. 'po number' -> 'PO Number', 'vat id' -> 'VAT ID') "
    "and trim the value. NEVER invent, drop, reorder, merge or split fields, and "
    "NEVER change the meaning or the numbers/IDs inside a value. Respond with ONLY "
    'a JSON array of {"label": "...", "value": "..."} objects and nothing else.'
)


def analyze_custom_fields(
    settings: Settings, pairs: List[tuple]
) -> Optional[List[tuple]]:
    """Lightly professionalise user-added custom ``(label, value)`` fields.

    AI only fixes label casing/spacing and trims values — it never changes a
    value's meaning, count or order. Returns a same-length list of cleaned
    ``(label, value)`` tuples, or ``None`` to fall back to the raw input. Any
    malformed/short/mismatched response is rejected so a generated document is
    never silently corrupted.
    """
    if not ai_available(settings) or not pairs:
        return None
    payload = [{"label": str(l), "value": str(v)} for l, v in pairs]
    prompt = "Fields to clean:\n" + json.dumps(payload)
    raw = _complete(_CUSTOM_FIELDS_SYSTEM_PROMPT, prompt, settings, max_tokens=600)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except Exception:
            return None
    if not isinstance(data, list) or len(data) != len(pairs):
        return None
    out: List[tuple] = []
    for orig, item in zip(pairs, data):
        if not isinstance(item, dict):
            return None
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        # Guard: AI must not blank a field or mangle the value's meaning. If the
        # value's digits changed, distrust the whole response and fall back.
        if not label or not value:
            return None
        if _digits(value) != _digits(str(orig[1])):
            return None
        out.append((label, value))
    return out


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def message_tone_variants(text: str, settings: Settings) -> Optional[Dict[str, str]]:
    """Return {tone: rewritten_message} for gentle/neutral/firm, or None on failure.

    The deterministic content (amounts, dates) is owned by the caller; this only
    re-words. Any malformed/partial AI response yields None so the UI can fall
    back to the single template message.
    """
    if not ai_available(settings) or not text.strip():
        return None
    prompt = f"Message to rewrite in three tones:\n{text}"
    raw = _complete(_VARIANTS_SYSTEM_PROMPT, prompt, settings, max_tokens=1500)
    data = _extract_json(raw or "")
    if not isinstance(data, dict):
        return None
    out: Dict[str, str] = {}
    for tone in TONE_VARIANTS:
        value = data.get(tone)
        if isinstance(value, str) and value.strip():
            out[tone] = value.strip()
    return out or None


# ---------------------------------------------------------------------------
# Reply-intent detection — classify a customer's reply (AI reads, Python acts)
# ---------------------------------------------------------------------------
# Intent labels the classifier may return. Python maps these to next steps; the
# AI never decides the action itself.
REPLY_INTENTS: List[str] = [
    "promise_to_pay",
    "already_paid",
    "dispute",
    "question",
    "not_interested",
    "out_of_office",
    "other",
]

_INTENT_SYSTEM_PROMPT = (
    "You classify a customer's reply to a payment reminder, quote follow-up, or "
    "sales message. Choose exactly one intent from this list: "
    + ", ".join(REPLY_INTENTS)
    + ". Definitions: promise_to_pay = says they will pay (optionally a date); "
    "already_paid = claims payment was already made; dispute = disputes the "
    "amount/work/invoice; question = asks for info (e.g. resend, details); "
    "not_interested = declines or wants to stop; out_of_office = auto-reply or "
    "away; other = none of these. Also extract a promised_date if the customer "
    "states one (ISO YYYY-MM-DD, else null), and give a one-line neutral "
    "summary. Respond with ONLY a JSON object: "
    '{"intent": "...", "confidence": 0.0-1.0, "promised_date": "YYYY-MM-DD or null", '
    '"summary": "..."} and nothing else. Do not invent facts.'
)


def classify_reply(text: str, settings: Settings) -> Optional[Dict[str, object]]:
    """Classify a customer reply. Returns a dict or None on any failure.

    Shape: ``{"intent": str, "confidence": float, "promised_date": str|None,
    "summary": str}``. The ``intent`` is always one of ``REPLY_INTENTS`` (falls
    back to "other" if the model returns something unexpected). The caller maps
    the intent to a suggested next step deterministically — AI never acts.
    """
    if not ai_available(settings) or not text.strip():
        return None
    from datetime import date

    # Tell the model today's date so relative dates ("next Friday") resolve.
    prompt = f"Today's date is {date.today().isoformat()}.\n\nCustomer reply:\n{text}"
    raw = _complete(_INTENT_SYSTEM_PROMPT, prompt, settings, max_tokens=300)
    data = _extract_json(raw or "")
    if not isinstance(data, dict):
        return None
    intent = str(data.get("intent", "")).strip().lower()
    if intent not in REPLY_INTENTS:
        intent = "other"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    promised = data.get("promised_date")
    promised_date = str(promised).strip() if promised not in (None, "", "null") else None
    summary = str(data.get("summary", "")).strip()
    return {
        "intent": intent,
        "confidence": max(0.0, min(1.0, confidence)),
        "promised_date": promised_date,
        "summary": summary,
    }
