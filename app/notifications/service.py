"""Idempotent notification delivery service — prevents duplicate sends by dedup_key."""
from app.schemas.notification import Notification,NotificationStatus

_sent_notifications: dict[str, Notification]={}

def is_duplicate(dedup_key: str) -> bool:
    """Check if a notification with this dedup key has already been sent."""
    return dedup_key in _sent_notifications

def send_notification(notification: Notification) -> Notification:
    """Try to send a notification.

    If a notification with the same dedup_key was already sent, skip it and return it with status=SKIPPED.
    Otherwise, mark it SENT, store it, and return it.
    """
    if is_duplicate(notification.dedup_key):
        notification.status=NotificationStatus.SKIPPED
        return notification

    else:
        notification.status =NotificationStatus.SENT
        _sent_notifications[notification.dedup_key]=notification
        return notification


