"""Tests for Ops notification service idempotency and retry mechanics."""

from unittest.mock import MagicMock
import pytest
from app.notifications.service import OpsNotificationService
from app.schemas.notification import Notification, NotificationPayload, NotificationStatus


@pytest.fixture
def sample_notification():
    """Return a sample Ops notification fixture."""
    return Notification(
        dedup_key="ops_ticket_TCK-9999",
        recipient_id="ops_team",
        type="at_risk_nudge",  # تم التغيير للقيمة المقبولة في الـ Enum
        payload=NotificationPayload(
            title="New Escalation Ticket Created",
            body="High latency detected in authentication service",
            metadata={"ticket_id": "TCK-9999"},
        ),
    )


def test_ops_notification_delivery_success(sample_notification, monkeypatch):
    """Test successful delivery of a new ticket notification."""
    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_session.exec.return_value.first.return_value = None
    mock_db.get_session_maker.return_value.__enter__.return_value = mock_session
    monkeypatch.setattr("app.notifications.service.DatabaseService", lambda: mock_db)

    service = OpsNotificationService()
    result = service.notify_new_ticket(sample_notification)

    assert result.status == NotificationStatus.SENT


def test_ops_notification_deduplication(sample_notification, monkeypatch):
    """Test skipping duplicate notifications if dedup_key is already SENT."""
    mock_db = MagicMock()
    mock_session = MagicMock()

    existing_record = MagicMock()
    existing_record.status = NotificationStatus.SENT
    mock_session.exec.return_value.first.return_value = existing_record

    mock_db.get_session_maker.return_value.__enter__.return_value = mock_session
    monkeypatch.setattr("app.notifications.service.DatabaseService", lambda: mock_db)

    service = OpsNotificationService()
    result = service.notify_new_ticket(sample_notification)

    assert result.status == NotificationStatus.SKIPPED