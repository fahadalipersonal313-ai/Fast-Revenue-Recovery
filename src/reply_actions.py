"""Deterministic next-step suggestions for a classified customer reply.

This is the safety boundary for the reply-intent feature: the AI only *reads*
the customer's text and returns an intent label (see ``ai_helper.classify_reply``);
the actual recommended action, urgency and whether a human must step in are
decided here, in plain Python — never by the model.

Nothing here sends anything or changes a record. It only produces advice the
user sees in the Approval Queue.
"""

from __future__ import annotations

from typing import Dict, Optional

# intent -> (recommended next step, needs_human, is_good_news)
_INTENT_ACTIONS: Dict[str, Dict[str, object]] = {
    "promise_to_pay": {
        "action": "Log the promised date and schedule a follow-up for the day after. "
                  "No further chasing until then.",
        "needs_human": False,
        "tone": "positive",
    },
    "already_paid": {
        "action": "Do NOT send another reminder. Verify against your records and, if "
                  "confirmed, mark the item as paid.",
        "needs_human": True,
        "tone": "positive",
    },
    "dispute": {
        "action": "Pause all reminders. A human must review the dispute before any "
                  "further contact.",
        "needs_human": True,
        "tone": "warning",
    },
    "question": {
        "action": "Answer the customer's question (e.g. resend the invoice or details), "
                  "then resume the normal follow-up schedule.",
        "needs_human": False,
        "tone": "neutral",
    },
    "not_interested": {
        "action": "Stop follow-ups for this item. Mark it lost/closed unless you want a "
                  "final courtesy reply.",
        "needs_human": False,
        "tone": "neutral",
    },
    "out_of_office": {
        "action": "Auto-reply detected — no action needed. Postpone the next follow-up by "
                  "a few days.",
        "needs_human": False,
        "tone": "neutral",
    },
    "other": {
        "action": "Could not categorise this reply automatically — please read it and "
                  "decide the next step.",
        "needs_human": True,
        "tone": "neutral",
    },
}


def suggest_next_step(intent: str) -> Dict[str, object]:
    """Return the deterministic advice for a classified intent.

    Always returns a dict with ``action`` (str), ``needs_human`` (bool) and
    ``tone`` (str). Unknown intents fall back to the cautious "other" entry.
    """
    return dict(_INTENT_ACTIONS.get(intent, _INTENT_ACTIONS["other"]))


def describe_classification(result: Optional[Dict[str, object]]) -> Dict[str, object]:
    """Combine an ``ai_helper.classify_reply`` result with its next-step advice.

    ``result`` may be None (AI unavailable/failed); in that case we return the
    cautious "other" advice so the UI always has something to show.
    """
    intent = str((result or {}).get("intent") or "other")
    advice = suggest_next_step(intent)
    advice["intent"] = intent
    advice["confidence"] = float((result or {}).get("confidence") or 0.0)
    advice["promised_date"] = (result or {}).get("promised_date")
    advice["summary"] = str((result or {}).get("summary") or "")
    return advice
