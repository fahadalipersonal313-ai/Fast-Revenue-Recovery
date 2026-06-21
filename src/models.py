"""Structured Pydantic models for agent decisions.

Every specialist agent returns one of these typed objects, never a loose dict.
The supervisor and the approval queue consume them. Keeping these models small
and explicit is what lets us validate agent output and keep the AI layer from
silently changing financial fields.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------
class RecordType(str, Enum):
    INVOICE = "invoice"
    QUOTE = "quote"
    LEAD = "lead"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Priority(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InvoiceStage(str, Enum):
    NOT_DUE = "Not due"
    COURTESY_REMINDER = "Courtesy reminder"
    STANDARD_REMINDER = "Standard reminder"
    FIRM_REMINDER = "Firm reminder"
    MISSED_PROMISE_FOLLOW_UP = "Missed promise follow up"
    FINAL_INTERNAL_ESCALATION = "Final internal escalation"
    PAYMENT_PLAN_DISCUSSION = "Payment plan discussion"
    HUMAN_REVIEW = "Human review"


class QuoteClass(str, Enum):
    ACTIVE = "active"
    WARM = "warm"
    COLD = "cold"
    WON = "won"
    LOST = "lost"
    REVIEW_REQUIRED = "review required"


class LeadTemperature(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    DEAD = "dead"


class MessageChannel(str, Enum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class MessageKind(str, Enum):
    COURTESY_REMINDER = "courtesy_payment_reminder"
    STANDARD_REMINDER = "standard_payment_reminder"
    FIRM_REMINDER = "firm_payment_reminder"
    MISSED_PROMISE_REMINDER = "missed_promise_reminder"
    FINAL_ESCALATION_DRAFT = "final_escalation_draft"
    QUOTE_FOLLOW_UP = "quote_follow_up"
    LEAD_FOLLOW_UP = "lead_follow_up"
    PRICE_OBJECTION_RESPONSE = "price_objection_response"
    APPOINTMENT_FOLLOW_UP = "appointment_follow_up"
    PAYMENT_THANK_YOU = "payment_thank_you"
    QUOTE_ACCEPTANCE_THANK_YOU = "quote_acceptance_thank_you"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
class GeneratedMessage(BaseModel):
    channel: MessageChannel
    kind: MessageKind
    subject: Optional[str] = None  # used for email only
    body: str
    ai_improved: bool = False


# ---------------------------------------------------------------------------
# Specialist decisions
# ---------------------------------------------------------------------------
class InvoiceDecision(BaseModel):
    record_type: RecordType = RecordType.INVOICE
    customer_name: str
    reference: str = Field(default="", description="Invoice number")
    amount: float = 0.0
    days_overdue: int = 0
    is_overdue: bool = False
    is_disputed: bool = False
    missed_promise: bool = False
    reminder_count: int = 0
    risk_level: RiskLevel = RiskLevel.NONE
    stage: InvoiceStage = InvoiceStage.NOT_DUE
    priority: Priority = Priority.NONE
    priority_score: float = 0.0
    next_action: str = ""
    next_follow_up_date: Optional[date] = None
    needs_human_review: bool = False
    reasons: List[str] = Field(default_factory=list)
    messages: List[GeneratedMessage] = Field(default_factory=list)


class QuoteDecision(BaseModel):
    record_type: RecordType = RecordType.QUOTE
    client_name: str
    reference: str = Field(default="", description="Quote number")
    amount: float = 0.0
    days_since_sent: int = 0
    follow_up_count: int = 0
    classification: QuoteClass = QuoteClass.ACTIVE
    buying_signals: List[str] = Field(default_factory=list)
    price_objection: bool = False
    missing_information: bool = False
    priority: Priority = Priority.NONE
    priority_score: float = 0.0
    next_action: str = ""
    next_follow_up_date: Optional[date] = None
    needs_human_review: bool = False
    reasons: List[str] = Field(default_factory=list)
    messages: List[GeneratedMessage] = Field(default_factory=list)


class LeadDecision(BaseModel):
    record_type: RecordType = RecordType.LEAD
    lead_name: str
    reference: str = ""
    estimated_value: float = 0.0
    days_since_contact: int = 0
    buying_signals: List[str] = Field(default_factory=list)
    urgency: bool = False
    budget_signal: bool = False
    price_sensitive: bool = False
    missing_information: bool = False
    lead_score: int = 0
    temperature: LeadTemperature = LeadTemperature.COLD
    priority: Priority = Priority.NONE
    priority_score: float = 0.0
    next_action: str = ""
    next_follow_up_date: Optional[date] = None
    stop_follow_ups: bool = False
    needs_human_review: bool = False
    score_explanation: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    messages: List[GeneratedMessage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Supervisor output
# ---------------------------------------------------------------------------
class SupervisorDecision(BaseModel):
    record_type: RecordType
    name: str
    reference: str = ""
    amount: float = 0.0
    priority: Priority = Priority.NONE
    priority_score: float = 0.0
    recommended_action: str = ""
    reason: str = ""
    suggested_message: str = ""
    suggested_channel: MessageChannel = MessageChannel.WHATSAPP
    next_follow_up_date: Optional[date] = None
    requires_approval: bool = True
    blocked_actions: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)
