"""Escalation trigger interface and default scaffold implementation."""

from typing import Protocol

from app.core.logging import logger
from app.schemas.escalation import (
    EscalationTriggerRequest,
    EscalationTriggerResult,
    TicketStatus,
)


class EscalationTrigger(Protocol):
    """Interface used by answering and proactive flows to escalate issues."""

    async def trigger(self, request: EscalationTriggerRequest) -> EscalationTriggerResult:
        """Trigger human escalation for a validated request."""
        ...


class NoopEscalationTrigger:
    """Scaffold trigger.

    This implementation does not create a real external ticket yet.
    It validates the request, logs the escalation, and returns a stable result.
    """

    async def trigger(self, request: EscalationTriggerRequest) -> EscalationTriggerResult:
        logger.info(
            "escalation_triggered",
            source=request.source.value,
            reason=request.reason,
            status=request.ticket.status.value,
            session_id=request.session_id,
            user_id=request.user_id,
        )

        return EscalationTriggerResult(
            triggered=True,
            status=TicketStatus.OPEN,
            ticket_id=None,
            message="Escalation captured by scaffold trigger. No external ticket was created.",
        )


escalation_trigger: EscalationTrigger = NoopEscalationTrigger()