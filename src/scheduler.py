"""Scheduled daily analysis using APScheduler.

The job reviews all active records, rebuilds the ranked recovery plan, tops up
the approval queue and writes a daily summary to the decision log. It never
sends a message — that is always a human action via the approval queue.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

from . import database as db
from .config import Settings
from .memory import AgentMemory


def load_active_records(memory: AgentMemory) -> Dict[str, List[Dict[str, Any]]]:
    """Reload normalised record snapshots that are still open, grouped by type."""
    rows = db.query(
        "SELECT record_type, payload_json FROM records WHERE outcome = 'open'",
        path=memory.path,
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {"invoice": [], "quote": [], "lead": []}
    for row in rows:
        try:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        grouped.setdefault(row["record_type"], []).append(payload)
    return grouped


def run_daily_analysis(
    memory: AgentMemory, settings: Settings, on_date: Optional[date] = None
) -> Dict[str, Any]:
    """Execute one analysis pass and return a summary. Safe to call manually."""
    # Imported here to avoid a circular import at module load time.
    from .approval_engine import analyze_and_queue, queue_counts

    run_date = (on_date or date.today()).isoformat()
    records = load_active_records(memory)
    plan = analyze_and_queue(memory, settings, records)

    high_priority = sum(1 for s in plan if s.priority.value in {"high", "critical"})
    summary = {
        "date": run_date,
        "invoices_reviewed": len(records.get("invoice", [])),
        "quotes_reviewed": len(records.get("quote", [])),
        "leads_reviewed": len(records.get("lead", [])),
        "plan_items": len(plan),
        "high_priority": high_priority,
        "pending_approvals": queue_counts(memory).get("pending", 0),
    }
    memory.log_decision(
        "system", "", "", "daily_run",
        json.dumps(summary) + " (no messages were sent)",
    )
    return summary


class RecoveryScheduler:
    """Thin wrapper around an APScheduler BackgroundScheduler.

    The scheduler is optional; if APScheduler is not installed the app still
    runs and the daily analysis can be triggered manually.
    """

    def __init__(self, memory: AgentMemory, settings: Settings) -> None:
        self.memory = memory
        self.settings = settings
        self._scheduler = None
        self._job_id = "daily_recovery_analysis"

    def available(self) -> bool:
        try:
            import apscheduler  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> bool:
        if not self.available():
            return False
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        if self._scheduler is not None:
            return True
        hour, minute = self._parse_time(self.settings.daily_analysis_time)
        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            self._job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id=self._job_id,
            replace_existing=True,
        )
        self._scheduler.start()
        return True

    def reschedule(self, time_str: str) -> bool:
        self.settings.daily_analysis_time = time_str
        if self._scheduler is None:
            return self.start()
        from apscheduler.triggers.cron import CronTrigger

        hour, minute = self._parse_time(time_str)
        self._scheduler.reschedule_job(
            self._job_id, trigger=CronTrigger(hour=hour, minute=minute)
        )
        return True

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def next_run_time(self):
        if self._scheduler is None:
            return None
        job = self._scheduler.get_job(self._job_id)
        return getattr(job, "next_run_time", None)

    def _job(self) -> None:
        run_daily_analysis(self.memory, self.settings)

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        try:
            hour_s, minute_s = str(time_str).split(":")[:2]
            return int(hour_s) % 24, int(minute_s) % 60
        except (ValueError, AttributeError):
            return 8, 0
