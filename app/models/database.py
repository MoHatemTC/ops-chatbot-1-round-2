"""Database models for the application."""

from app.models.escalation_ticket import EscalationTicket
from app.models.thread import Thread

__all__ = ["Thread", "EscalationTicket"]
