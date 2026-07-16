"""Schemas for escalation tickets and conversation handoff summaries."""
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class TicketStatus(str, Enum):
    """Allowed ticket statuses for human escalation."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Ticket(BaseModel):
    """Shared escalation ticket contract.

    This is the common shape used by answering and proactive flows when
    an issue needs human follow-up.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    problem: str = Field(
        ...,
        min_length=1,
        max_length=800,
        description="The learner's main problem or unresolved request.",
    )
    what_was_tried: str = Field(
        ...,
        alias="what-was-tried",
        min_length=1,
        max_length=1000,
        description="What the assistant or learner already tried before escalation.",
    )
    context: str = Field(
        ...,
        min_length=1,
        max_length=1200,
        description="Relevant non-sensitive context needed by the human operator.",
    )
    suggested_next_step: str = Field(
        ...,
        alias="suggested-next-step",
        min_length=1,
        max_length=800,
        description="Recommended next action for the Operations team.",
    )
    status: TicketStatus = Field(
        default=TicketStatus.OPEN,
        description="Current ticket status.",
    )


class ConversationSummary(BaseModel):
    """Concise privacy-preserving summary for human handoff."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        ...,
        min_length=1,
        max_length=800,
        description="Short summary of the issue without raw chat transcript.",
    )
    user_goal: str = Field(
        ...,
        min_length=1,
        max_length=400,
        description="What the learner is trying to achieve.",
    )
    key_facts: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Important non-sensitive facts needed for follow-up.",
    )
    assistant_actions: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Actions already taken by the assistant.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Questions the human operator may need to ask.",
    )
    privacy_note: str = Field(
        default="Raw personal data and full conversation history are excluded unless required for support.",
        max_length=300,
        description="Privacy handling note.",
    )


class EscalationSource(str, Enum):
    """Where the escalation came from."""

    ANSWERING = "answering"
    PROACTIVE = "proactive"


class EscalationTriggerRequest(BaseModel):
    """Input passed by answering/proactive flows to the escalation trigger."""

    model_config = ConfigDict(extra="forbid")

    source: EscalationSource = Field(
        ...,
        description="Flow that created the escalation.",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Why this issue needs human escalation.",
    )
    ticket: Ticket
    conversation_summary: ConversationSummary
    session_id: str | None = Field(
        default=None,
        description="Session identifier for internal traceability.",
    )
    user_id: str | None = Field(
        default=None,
        description="User identifier for internal traceability.",
    )


class EscalationTriggerResult(BaseModel):
    """Result returned after attempting to trigger escalation."""

    triggered: bool = Field(..., description="Whether escalation was accepted.")
    status: TicketStatus = Field(default=TicketStatus.OPEN)
    ticket_id: str | None = Field(
        default=None,
        description="External or internal ticket identifier, if available.",
    )
    message: str = Field(
        default="Escalation accepted by scaffold trigger.",
        description="Human-readable result message.",
    )