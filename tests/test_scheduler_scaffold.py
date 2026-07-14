"""Test notification sending failure and success."""
from app.schemas.notification import Notification, NotificationType, NotificationPayload, NotificationStatus
from app.scheduler.runner import run_notification
import pytest

count = 0

@pytest.fixture(autouse=True)
def reset_count():
    """Reset the flaky_deliver call counter before each test."""
    global count
    count = 0

def flaky_deliver(notification: Notification) -> Notification:
    """Simulates a delivery function that fails twice and succeeds in the third.

    Used to test that run_notification marks the notification SENT.
    """
    global count
    count += 1
    if count < 3:
        raise Exception("Failed to send notification")
    notification.status = NotificationStatus.SENT
    return notification

def always_fails(notification: Notification) -> Notification:
    """Simulate a delivery function that always fails.

    Used to verify that run_notification exhausts all retry attempts
    and marks the notification FAILED instead of crashing.
    """
    raise Exception("Failed to send notification")


def test_retry_succeeds_after_failures():
    """Verify that run_notification retries on failure.

    Used to verify that run_notification retries on failure and eventually
    succeeds, given a deliver_fn that fails twice then succeeds.
    """
    notification = Notification(
        recipient_id="abc123",
        type=NotificationType.SESSION_REMINDER,
        payload=NotificationPayload(title="Reminder", body="Session starts soon"),
        dedup_key="learner_abc123:session_789:test_retry",
    )

    result = run_notification(notification, deliver_fn=flaky_deliver)

    assert result.status == NotificationStatus.SENT

def test_all_retries_exhausted_marks_failed():
    """Verify that when delivery always fails.

    run_notification exhausts all retry attempts and marks the notification FAILED
    instead of crashing.
    """
    notification = Notification(
        recipient_id="abc123",
        type=NotificationType.SESSION_REMINDER,
        payload=NotificationPayload(title="Reminder", body="Session starts soon"),
        dedup_key="learner_abc123:session_999:test_failure",
    )

    result = run_notification(notification, deliver_fn=always_fails)

    assert result.status == NotificationStatus.FAILED
def test_duplicate_call_does_not_resend():
    """Verify calling run_notification twice with the same dedup_key.

    Used to test duplictes -> does not resend — the second call should be marked SKIPPED.
    """
    n1 = Notification(
    recipient_id="abc123",
    type=NotificationType.SESSION_REMINDER,
    payload=NotificationPayload(title="Reminder", body="Session starts soon"),
    dedup_key="learner_abc123:session_456:24h_before",
     )
    result1 = run_notification(n1)
    assert result1.status == NotificationStatus.SENT

    n2 = Notification(
    recipient_id="abc123",
    type=NotificationType.SESSION_REMINDER,
    payload=NotificationPayload(title="Reminder", body="Session starts soon"),
    dedup_key="learner_abc123:session_456:24h_before",
    )
    result2 = run_notification(n2)
    assert result2.status == NotificationStatus.SKIPPED
