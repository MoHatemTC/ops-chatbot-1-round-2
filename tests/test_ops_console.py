"""Tests for Ops Console dashboard metrics, KPIs, and KB admin API."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.dashboards.metrics import (
    get_escalation_rate,
    get_resolution_time_estimate,
    get_support_metrics,
    get_support_volume,
)
from app.observability.kpis import (
    escalation_rate as kpi_escalation_rate,
    support_sessions_total,
    update_support_metrics,
)
from app.services.database import DatabaseService

db_service = DatabaseService()
TEST_EMAIL = "opsconsole_test@example.com"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Ensure no leftover test user exists before each test."""
    asyncio.run(db_service.delete_user_by_email(TEST_EMAIL))


@pytest.fixture
def sample_data():
    """Create a user, sessions, and an escalation ticket for testing metrics."""
    user = asyncio.run(db_service.create_user(email=TEST_EMAIL, password="hashed_pw", username="ops_tester"))
    session1 = asyncio.run(db_service.create_session(session_id="ops_test_session_1", user_id=user.id))
    session2 = asyncio.run(db_service.create_session(session_id="ops_test_session_2", user_id=user.id))
    ticket = asyncio.run(
        db_service.create_escalation_ticket(
            source="chat",
            reason="unresolved_question",
            status="open",
            problem="test problem",
            what_was_tried="test attempt",
            context="test context",
            suggested_next_step="test next step",
            summary="test summary",
            user_goal="test goal",
            key_facts=[],
            assistant_actions=[],
            open_questions=[],
            privacy_note="none",
            session_id=session1.id,
            user_id=str(user.id),
        )
    )
    return {"user": user, "sessions": [session1, session2], "ticket": ticket}


def _window():
    """Return a (start, end) window wide enough to include freshly created test rows."""
    end = datetime.now(timezone.utc) + timedelta(minutes=1)
    start = end - timedelta(days=1)
    return start, end


def test_get_support_volume_counts_sessions(sample_data):
    """Verify get_support_volume counts the sessions created in the window."""
    with db_service.get_session_maker() as session:
        start, end = _window()
        volume = get_support_volume(session, start, end)

    total = sum(row["count"] for row in volume)
    assert total == 2


def test_get_escalation_rate_nonzero(sample_data):
    """Verify get_escalation_rate computes ticket-count / session-count."""
    with db_service.get_session_maker() as session:
        start, end = _window()
        rate = get_escalation_rate(session, start, end)

    # 1 ticket over 2 sessions created in sample_data
    assert rate == pytest.approx(0.5)


def test_get_escalation_rate_zero_sessions():
    """Verify get_escalation_rate returns 0.0 when there are no sessions at all."""
    with db_service.get_session_maker() as session:
        # A window far in the past, unlikely to contain any real data.
        start = datetime(2000, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        rate = get_escalation_rate(session, start, end)

    assert rate == 0.0


def test_get_resolution_time_estimate_links_ticket_to_session(sample_data):
    """Verify resolution time estimate is computed for a ticket with a linked session."""
    with db_service.get_session_maker() as session:
        start, end = _window()
        estimates = get_resolution_time_estimate(session, start, end)

    assert len(estimates) == 1
    assert estimates[0]["ticket_id"] == sample_data["ticket"].id
    assert estimates[0]["estimated_resolution_seconds"] >= 0


def test_get_support_metrics_bundles_all_three(sample_data):
    """Verify get_support_metrics returns all three metrics together."""
    with db_service.get_session_maker() as session:
        start, end = _window()
        metrics = get_support_metrics(session, start, end)

    assert "support_volume" in metrics
    assert "escalation_rate" in metrics
    assert "resolution_time" in metrics


def test_update_support_metrics_sets_kpis(sample_data):
    """Verify update_support_metrics records values into the Prometheus KPI objects."""
    with db_service.get_session_maker() as session:
        start, end = _window()
        metrics = get_support_metrics(session, start, end)

    before = support_sessions_total._value.get()
    update_support_metrics(metrics)
    after = support_sessions_total._value.get()

    assert after >= before
    assert kpi_escalation_rate._value.get() == pytest.approx(metrics["escalation_rate"])

