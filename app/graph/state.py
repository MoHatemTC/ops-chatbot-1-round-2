"""Checkpointed graph state for Phase 1 orchestration."""

from typing import Annotated, Literal
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


EscalationReason = Literal[
    "explicit_human_request",
    "frustration",
    "repeated_failed_turns",
    "answer_signal",
]


class EscalationContext(BaseModel):
    """Structured escalation data stored in checkpointed graph state."""

    trigger_reason: EscalationReason
    problem: str
    what_was_tried: str
    context: str
    suggested_next_step: str
    summary: str
    user_goal: str
    key_facts: list[str] = Field(default_factory=list)
    assistant_actions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class SessionGraphState(BaseModel):
    """Phase 1 graph state for retrieve -> answer -> router -> escalate."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    session_id: str | None = None
    user_id: str | None = None
    long_term_memory: str = ""

    retrieved: bool = False
    answer_generated: bool = False

    failed_turn_count: int = 0
    frustration_detected: bool = False
    explicit_human_requested: bool = False
    answer_escalation_signal: bool = False
    answer_escalation_reason: str | None = None

    escalation_needed: bool = False
    escalation_context: EscalationContext | None = None
    ticket_id: str | None = None
    route_decision: Literal["answer", "escalate", "end"] | None = None