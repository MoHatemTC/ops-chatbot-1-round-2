"""Ticket persistence, lookup, status management, and Ops notification.

This module is the application service for Sprint 2 escalation tickets. It keeps
LangGraph nodes and FastAPI routes independent from SQLModel details, persists a
privacy-preserving handoff, and exposes a small notification contract that can
be replaced by the team's chosen Operations channel.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from prometheus_client import Counter, Histogram
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import logger
from app.models.escalation_ticket import EscalationTicket
from app.schemas.escalation import (
    ConversationSummary,
    EscalationSource,
    EscalationTriggerRequest,
    EscalationTriggerResult,
    Ticket,
    TicketStatus,
)
from app.services.database import DatabaseService, database_service

_MAX_PAGE_SIZE = 100
_RETRY_ATTEMPTS = 3


ticket_service_operations_total = Counter(
    "ticket_service_operations_total",
    "Ticket-service operations grouped by operation and outcome.",
    ["operation", "outcome"],
)

ticket_service_duration_seconds = Histogram(
    "ticket_service_duration_seconds",
    "Time spent performing ticket-service operations.",
    ["operation"],
    buckets=[0.005, 0.01, 0.05, 0.1, 0.3, 0.5, 1.0, 2.0, 5.0],
)

ops_ticket_notifications_total = Counter(
    "ops_ticket_notifications_total",
    "Operations ticket notifications grouped by outcome.",
    ["outcome"],
)


class TicketServiceError(RuntimeError):
    """Base exception for ticket-service failures."""


class TicketNotFoundError(TicketServiceError):
    """Raised when the requested ticket does not exist."""

    def __init__(self, ticket_id: str) -> None:
        """Initialize the exception with the missing ticket identifier."""
        super().__init__(f"Ticket {ticket_id!r} was not found.")
        self.ticket_id = ticket_id


@dataclass(frozen=True, slots=True)
class OpsTicketNotification:
    """Minimal privacy-preserving payload sent to the Operations notifier."""

    ticket_id: str
    source: str
    status: str
    problem: str
    summary: str
    suggested_next_step: str


class OpsNotifier(Protocol):
    """Contract implemented by an Operations notification adapter."""

    def notify_ticket_created(self, notification: OpsTicketNotification) -> Awaitable[None] | None:
        """Notify Operations that a support ticket was created."""
        ...


class LoggingOpsNotifier:
    """Default notification adapter that emits the notification contract to logs.

    The project has not selected its final external ticketing workspace yet. This
    adapter keeps the service functional and observable while preserving an
    injectable seam for email, Slack, or another approved Operations channel.
    """

    def notify_ticket_created(self, notification: OpsTicketNotification) -> None:
        """Emit a structured Operations notification event."""
        logger.info(
            "ops_ticket_notification",
            ticket_id=notification.ticket_id,
            source=notification.source,
            status=notification.status,
            problem=notification.problem,
            summary=notification.summary,
            suggested_next_step=notification.suggested_next_step,
        )


class TicketService:
    """Coordinate the internal ticket store and Operations notifications."""

    def __init__(
        self,
        *,
        database: DatabaseService | None = None,
        notifier: OpsNotifier | None = None,
    ) -> None:
        """Initialize the service with replaceable database and notifier seams."""
        self._database = database or database_service
        self._notifier = notifier or LoggingOpsNotifier()

    async def create_ticket(self, request: EscalationTriggerRequest) -> EscalationTriggerResult:
        """Persist one validated escalation request and notify Operations.

        Ticket persistence is the source of truth. If notification delivery fails
        after its retries, the stored ticket remains available through the Ops API
        and the result still contains its confirmed internal ticket ID.
        """
        operation = "create"
        ticket = self._record_from_request(request)

        try:
            with ticket_service_duration_seconds.labels(operation=operation).time():
                stored = await self._persist_ticket(ticket)
            ticket_service_operations_total.labels(operation=operation, outcome="success").inc()
        except Exception:
            ticket_service_operations_total.labels(operation=operation, outcome="error").inc()
            logger.exception(
                "ticket_creation_failed",
                source=request.source.value,
                session_id=request.session_id,
                user_id=request.user_id,
            )
            raise

        notification_delivered = await self._notify_ops(stored)
        message = (
            f"Escalation stored and Operations notified with ticket ID {stored.id}."
            if notification_delivered
            else (
                f"Escalation stored with ticket ID {stored.id}; "
                "the Operations notification could not be confirmed."
            )
        )
        return EscalationTriggerResult(
            triggered=True,
            status=TicketStatus(stored.status),
            ticket_id=stored.id,
            message=message,
        )

    async def list_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[EscalationTicket]:
        """Return tickets newest first, optionally filtered by status."""
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        if not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {_MAX_PAGE_SIZE}")

        operation = "list"
        try:
            with ticket_service_duration_seconds.labels(operation=operation).time():
                tickets = await self._list_tickets(status=status, offset=offset, limit=limit)
            ticket_service_operations_total.labels(operation=operation, outcome="success").inc()
            return tickets
        except Exception:
            ticket_service_operations_total.labels(operation=operation, outcome="error").inc()
            logger.exception(
                "ticket_list_failed",
                status=status.value if status is not None else None,
                offset=offset,
                limit=limit,
            )
            raise

    async def get_ticket(self, ticket_id: str) -> EscalationTicket:
        """Return one ticket or raise ``TicketNotFoundError``."""
        normalized_id = self._normalize_ticket_id(ticket_id)
        operation = "get"

        try:
            with ticket_service_duration_seconds.labels(operation=operation).time():
                ticket = await self._get_ticket(normalized_id)
            if ticket is None:
                ticket_service_operations_total.labels(operation=operation, outcome="not_found").inc()
                raise TicketNotFoundError(normalized_id)
            ticket_service_operations_total.labels(operation=operation, outcome="success").inc()
            return ticket
        except TicketNotFoundError:
            raise
        except Exception:
            ticket_service_operations_total.labels(operation=operation, outcome="error").inc()
            logger.exception("ticket_get_failed", ticket_id=normalized_id)
            raise

    async def resolve_ticket(self, ticket_id: str) -> EscalationTicket:
        """Mark a ticket resolved and return the updated record.

        Resolving an already-resolved ticket is intentionally idempotent so API
        retries do not create an error or alter unrelated data.
        """
        normalized_id = self._normalize_ticket_id(ticket_id)
        operation = "resolve"

        try:
            with ticket_service_duration_seconds.labels(operation=operation).time():
                ticket = await self._resolve_ticket(normalized_id)
            if ticket is None:
                ticket_service_operations_total.labels(operation=operation, outcome="not_found").inc()
                raise TicketNotFoundError(normalized_id)
            ticket_service_operations_total.labels(operation=operation, outcome="success").inc()
            return ticket
        except TicketNotFoundError:
            raise
        except Exception:
            ticket_service_operations_total.labels(operation=operation, outcome="error").inc()
            logger.exception("ticket_resolve_failed", ticket_id=normalized_id)
            raise

    @staticmethod
    def _record_from_request(request: EscalationTriggerRequest) -> EscalationTicket:
        """Convert the validated shared request into the database record."""
        ticket = request.ticket
        summary = request.conversation_summary
        return EscalationTicket(
            id=f"esc_{uuid4().hex[:12]}",
            source=request.source.value,
            reason=request.reason,
            status=ticket.status.value,
            problem=ticket.problem,
            what_was_tried=ticket.what_was_tried,
            context=ticket.context,
            suggested_next_step=ticket.suggested_next_step,
            summary=summary.summary,
            user_goal=summary.user_goal,
            key_facts=list(summary.key_facts),
            assistant_actions=list(summary.assistant_actions),
            open_questions=list(summary.open_questions),
            privacy_note=summary.privacy_note,
            session_id=request.session_id,
            user_id=request.user_id,
        )

    @staticmethod
    def _notification_from_ticket(ticket: EscalationTicket) -> OpsTicketNotification:
        """Build the small payload allowed to leave the ticket service."""
        return OpsTicketNotification(
            ticket_id=ticket.id,
            source=ticket.source,
            status=ticket.status,
            problem=ticket.problem,
            summary=ticket.summary,
            suggested_next_step=ticket.suggested_next_step,
        )

    @staticmethod
    def _normalize_ticket_id(ticket_id: str) -> str:
        """Validate and normalize a caller-supplied ticket identifier."""
        normalized = ticket_id.strip()
        if not normalized:
            raise ValueError("ticket_id must not be empty")
        return normalized

    @retry(
        retry=retry_if_exception_type(SQLAlchemyError),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
        reraise=True,
    )
    async def _persist_ticket(self, ticket: EscalationTicket) -> EscalationTicket:
        """Persist a stable-ID ticket safely across transient database retries."""
        with self._database.get_session_maker() as session:
            existing = session.get(EscalationTicket, ticket.id)
            if existing is not None:
                return existing

            session.add(ticket)
            session.commit()
            session.refresh(ticket)
            logger.info(
                "ticket_created",
                ticket_id=ticket.id,
                source=ticket.source,
                status=ticket.status,
                session_id=ticket.session_id,
                user_id=ticket.user_id,
            )
            return ticket

    @retry(
        retry=retry_if_exception_type(SQLAlchemyError),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
        reraise=True,
    )
    async def _list_tickets(
        self,
        *,
        status: TicketStatus | None,
        offset: int,
        limit: int,
    ) -> list[EscalationTicket]:
        """Execute the paginated ticket query."""
        with self._database.get_session_maker() as session:
            statement = select(EscalationTicket)
            if status is not None:
                statement = statement.where(EscalationTicket.status == status.value)
            statement = statement.order_by(col(EscalationTicket.created_at).desc()).offset(offset).limit(limit)
            return list(session.exec(statement).all())

    @retry(
        retry=retry_if_exception_type(SQLAlchemyError),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
        reraise=True,
    )
    async def _get_ticket(self, ticket_id: str) -> EscalationTicket | None:
        """Read one ticket from the internal store."""
        with self._database.get_session_maker() as session:
            return session.get(EscalationTicket, ticket_id)

    @retry(
        retry=retry_if_exception_type(SQLAlchemyError),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
        reraise=True,
    )
    async def _resolve_ticket(self, ticket_id: str) -> EscalationTicket | None:
        """Set one stored ticket to the resolved state."""
        with self._database.get_session_maker() as session:
            ticket = session.get(EscalationTicket, ticket_id)
            if ticket is None:
                return None
            if ticket.status != TicketStatus.RESOLVED.value:
                ticket.status = TicketStatus.RESOLVED.value
                session.add(ticket)
                session.commit()
                session.refresh(ticket)
                logger.info("ticket_resolved", ticket_id=ticket.id)
            return ticket

    @retry(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
        reraise=True,
    )
    async def _deliver_notification(self, notification: OpsTicketNotification) -> None:
        """Deliver one notification through a sync or async adapter."""
        result = self._notifier.notify_ticket_created(notification)
        if inspect.isawaitable(result):
            await result

    async def _notify_ops(self, ticket: EscalationTicket) -> bool:
        """Notify Operations without deleting or hiding an already stored ticket."""
        notification = self._notification_from_ticket(ticket)
        try:
            await self._deliver_notification(notification)
            ops_ticket_notifications_total.labels(outcome="success").inc()
            return True
        except Exception:
            ops_ticket_notifications_total.labels(outcome="error").inc()
            logger.exception("ops_ticket_notification_failed", ticket_id=ticket.id)
            return False


_default_ticket_service = TicketService()


async def create_ticket(request: EscalationTriggerRequest) -> EscalationTriggerResult:
    """Persist and notify for an already validated escalation request."""
    return await _default_ticket_service.create_ticket(request)


async def list_tickets(
    *,
    status: TicketStatus | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[EscalationTicket]:
    """List tickets through the default service instance."""
    return await _default_ticket_service.list_tickets(status=status, offset=offset, limit=limit)


async def get_ticket(ticket_id: str) -> EscalationTicket:
    """Fetch one ticket through the default service instance."""
    return await _default_ticket_service.get_ticket(ticket_id)


async def resolve_ticket(ticket_id: str) -> EscalationTicket:
    """Resolve one ticket through the default service instance."""
    return await _default_ticket_service.resolve_ticket(ticket_id)


def _build_request(
    *,
    source: EscalationSource,
    reason: str,
    problem: str,
    what_was_tried: str,
    context: str,
    suggested_next_step: str,
    summary: str,
    user_goal: str,
    key_facts: Sequence[str] | None = None,
    assistant_actions: Sequence[str] | None = None,
    open_questions: Sequence[str] | None = None,
    privacy_note: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    session_id: str | None = None,
    user_id: str | None = None,
) -> EscalationTriggerRequest:
    """Build the shared validated request used by answering and proactive flows."""
    summary_values: dict[str, object] = {
        "summary": summary,
        "user_goal": user_goal,
        "key_facts": list(key_facts or ()),
        "assistant_actions": list(assistant_actions or ()),
        "open_questions": list(open_questions or ()),
    }
    if privacy_note is not None:
        summary_values["privacy_note"] = privacy_note

    return EscalationTriggerRequest(
        source=source,
        reason=reason,
        ticket=Ticket.model_validate(
            {
                "problem": problem,
                "what_was_tried": what_was_tried,
                "context": context,
                "suggested_next_step": suggested_next_step,
                "status": status,
            }
        ),
        conversation_summary=ConversationSummary.model_validate(summary_values),
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
    key_facts: Sequence[str] | None = None,
    assistant_actions: Sequence[str] | None = None,
    open_questions: Sequence[str] | None = None,
    privacy_note: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    session_id: str | None = None,
    user_id: str | None = None,
) -> EscalationTriggerResult:
    """Create a ticket from the answering/escalation LangGraph flow."""
    request = _build_request(
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
    return await create_ticket(request)


async def trigger_proactive_escalation(
    *,
    reason: str,
    problem: str,
    what_was_tried: str,
    context: str,
    suggested_next_step: str,
    summary: str,
    user_goal: str,
    key_facts: Sequence[str] | None = None,
    assistant_actions: Sequence[str] | None = None,
    open_questions: Sequence[str] | None = None,
    privacy_note: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    session_id: str | None = None,
    user_id: str | None = None,
) -> EscalationTriggerResult:
    """Create a ticket from a proactive workflow."""
    request = _build_request(
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
    return await create_ticket(request)


__all__ = [
    "LoggingOpsNotifier",
    "OpsNotifier",
    "OpsTicketNotification",
    "TicketNotFoundError",
    "TicketService",
    "TicketServiceError",
    "create_ticket",
    "get_ticket",
    "list_tickets",
    "resolve_ticket",
    "trigger_answering_escalation",
    "trigger_proactive_escalation",
]