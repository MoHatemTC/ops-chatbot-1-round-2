"""Database model for persisted escalation tickets."""

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.models.base import BaseModel


class EscalationTicket(BaseModel, table=True):
    """Persisted escalation ticket record."""

    __tablename__ = "escalation_ticket"

    id: str = Field(primary_key=True)
    source: str
    reason: str
    status: str
    problem: str
    what_was_tried: str
    context: str
    suggested_next_step: str
    summary: str
    user_goal: str
    key_facts: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    assistant_actions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    open_questions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    privacy_note: str
    session_id: str | None = Field(default=None, index=True)
    user_id: str | None = Field(default=None, index=True)
