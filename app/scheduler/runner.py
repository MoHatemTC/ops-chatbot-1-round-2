"""Runner handles notification sending retries."""
from tenacity import retry, stop_after_attempt, wait_exponential
from app.schemas.notification import Notification, NotificationStatus
from app.notifications.service import send_notification


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def deliver_with_retry(notification: Notification, deliver_fn) -> Notification:
    """Attempt to deliver a notification via the idempotent service.

    Retries with exponential backoff if delivery raises an exception,
    waiting between 1 and 10 seconds between attempts.
    """
    return send_notification(notification, deliver_action=deliver_fn)

def run_notification(notification: Notification, deliver_fn=None) -> Notification:
    """Run a notification delivery job with retry/backoff.

    If all retry attempts are exhausted, mark the notification FAILED.
    """
    try:
        return deliver_with_retry(notification, deliver_fn)
    except Exception:
        notification.status = NotificationStatus.FAILED
        return notification

def run_scheduled_jobs(notifications: list[Notification], deliver_fn=None) -> list[Notification]:
    """Run a batch of notification jobs, delivering each with retry/backoff.

    Processes every notification in the list independently — one job
    failing does not stop the rest of the batch from running.
    """
    results = []
    for notification in notifications:
        result = run_notification(notification, deliver_fn=deliver_fn)
        results.append(result)
    return results