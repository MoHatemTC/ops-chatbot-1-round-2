"""Escalation trigger interface and default scaffold implementation."""

import logging
from typing import Protocol

try:
    from app.core.logging import logger
except ModuleNotFoundError:
    logger = logging.getLogger(__name__)

from app.schemas.escalation import (
    ConversationSummary,
    EscalationSource,
    EscalationTriggerRequest,
    EscalationTriggerResult,
    Ticket,
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
            status=request.ticket.status,
            ticket_id=None,
            message="Escalation captured by scaffold trigger. No external ticket was created.",
        )


escalation_trigger: EscalationTrigger = NoopEscalationTrigger()


async def trigger_escalation(request: EscalationTriggerRequest) -> EscalationTriggerResult:
    """Trigger an escalation request through the configured backend."""
    return await escalation_trigger.trigger(request)


async def create_escalation_request(
    *,
    source: EscalationSource,
    reason: str,
    problem: str,
    what_was_tried: str,
    context: str,
    suggested_next_step: str,
    summary: str,
    user_goal: str,
    key_facts: list[str] | None = None,
    assistant_actions: list[str] | None = None,
    open_questions: list[str] | None = None,
    privacy_note: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    session_id: str | None = None,
    user_id: str | None = None,
) -> EscalationTriggerRequest:
    """Build a validated escalation request for any caller flow."""
    summary_payload = {
        "summary": summary,
        "user_goal": user_goal,
        "key_facts": key_facts or [],
        "assistant_actions": assistant_actions or [],
        "open_questions": open_questions or [],
    }
    if privacy_note is not None:
        summary_payload["privacy_note"] = privacy_note

    return EscalationTriggerRequest(
        source=source,
        reason=reason,
        ticket=Ticket(
            problem=problem,
            what_was_tried=what_was_tried,
            context=context,
            suggested_next_step=suggested_next_step,
            status=status,
        ),
        conversation_summary=ConversationSummary(**summary_payload),
        session_id=session_id,
        user_id=user_id,
    )


async def trigger_answering_escalation(
    *,
    reason: str,
    problem: str,
    what_was_tried: str,
    context: str,
    suggested_next_step: str,
    summary: str,
    user_goal: str,
    key_facts: list[str] | None = None,
    assistant_actions: list[str] | None = None,
    open_questions: list[str] | None = None,
    privacy_note: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    session_id: str | None = None,
    user_id: str | None = None,
) -> EscalationTriggerResult:
    """Build and trigger an answering-flow escalation."""
    request = await create_escalation_request(
        source=EscalationSource.ANSWERING,
        reason=reason,
        problem=problem,
        what_was_tried=what_was_tried,
        context=context,
        suggested_next_step=suggested_next_step,
        summary=summary,
        user_goal=user_goal,
        key_facts=key_facts,
        assistant_actions=assistant_actions,
        open_questions=open_questions,
        privacy_note=privacy_note,
        status=status,
        session_id=session_id,
        user_id=user_id,
    )
    return await trigger_escalation(request)


async def trigger_proactive_escalation(
    *,
    reason: str,
    problem: str,
    what_was_tried: str,
    context: str,
    suggested_next_step: str,
    summary: str,
    user_goal: str,
    key_facts: list[str] | None = None,
    assistant_actions: list[str] | None = None,
    open_questions: list[str] | None = None,
    privacy_note: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    session_id: str | None = None,
    user_id: str | None = None,
) -> EscalationTriggerResult:
    """Build and trigger a proactive-flow escalation."""
    request = await create_escalation_request(
        source=EscalationSource.PROACTIVE,
        reason=reason,
        problem=problem,
        what_was_tried=what_was_tried,
        context=context,
        suggested_next_step=suggested_next_step,
        summary=summary,
        user_goal=user_goal,
        key_facts=key_facts,
        assistant_actions=assistant_actions,
        open_questions=open_questions,
        privacy_note=privacy_note,
        status=status,
        session_id=session_id,
        user_id=user_id,
    )
    return await trigger_escalation(request)
