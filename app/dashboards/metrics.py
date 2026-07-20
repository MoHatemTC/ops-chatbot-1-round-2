from sqlalchemy import func
from sqlmodel import select
from datetime import datetime

from app.models.session import Session as ChatSession
from app.models.escalation_ticket import EscalationTicket


def get_support_volume(session, start: datetime, end: datetime) -> list[dict]:
    """Return daily support session counts between start and end (inclusive)."""
    day = func.date(ChatSession.created_at)

    statement = (
        select(day.label("date"), func.count().label("count"))
        .where(ChatSession.created_at >= start)
        .where(ChatSession.created_at <= end)
        .group_by(day)
        .order_by(day)
    )

    results = session.exec(statement).all()
    return [{"date": row.date, "count": row.count} for row in results]


def get_ticket_count(session, start: datetime, end: datetime) -> int:
    """Return the total number of escalation tickets created between start and end."""
    statement = (
        select(func.count())
        .select_from(EscalationTicket)
        .where(EscalationTicket.created_at >= start)
        .where(EscalationTicket.created_at <= end)
    )
    return session.exec(statement).one()


def get_escalation_rate(session, start: datetime, end: datetime) -> float:
    """Return the fraction of sessions that resulted in an escalation ticket."""
    try:
        daily_counts = get_support_volume(session, start, end)
        sum_counts = sum(row["count"] for row in daily_counts)
        total_tickets = get_ticket_count(session, start, end)
        escalation_rate = total_tickets / sum_counts
        return escalation_rate
    except ZeroDivisionError:
        return 0.0


def get_resolution_time_estimate(session, start: datetime, end: datetime) -> list[dict]:
    """Estimate resolution time per ticket, as an approximation only.

    ASSUMPTION: EscalationTicket has no resolved_at/updated_at timestamp,
    and no message-level "last activity" timestamp is accessible outside
    LangGraph's internal checkpoint tables (out of platform-boundary scope
    for this task). As an approved fallback , this
    estimates resolution time as: ticket.created_at - session.created_at
    — i.e. how long the session had been running before escalation, NOT
    true time-to-resolution. Tickets with no linked session are excluded.
    This is a known limitation, to be revisited once real ticket-resolution
    tracking exists.
    """
    statement = (
        select(
            EscalationTicket.id.label("ticket_id"),
            EscalationTicket.created_at.label("ticket_created_at"),
            ChatSession.created_at.label("session_created_at"),
        )
        .join(ChatSession, EscalationTicket.session_id == ChatSession.id)
        .where(EscalationTicket.created_at >= start)
        .where(EscalationTicket.created_at <= end)
    )

    results = session.exec(statement).all()

    estimates = []
    for row in results:
        delta_seconds = (row.ticket_created_at - row.session_created_at).total_seconds()
        estimates.append(
            {
                "ticket_id": row.ticket_id,
                "estimated_resolution_seconds": delta_seconds,
            }
        )

    return estimates


def get_support_metrics(session, start: datetime, end: datetime) -> dict:
    """Return all Phase-1 support metrics for the given window."""
    return {
        "support_volume": get_support_volume(session, start, end),
        "escalation_rate": get_escalation_rate(session, start, end),
        "resolution_time": get_resolution_time_estimate(session, start, end),
    }
