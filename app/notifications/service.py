"""Idempotent notification delivery service — prevents duplicate sends by dedup_key."""
from sqlmodel import select
import json
from app.services.database import DatabaseService
from app.models.notification import NotificationRecord
from app.schemas.notification import Notification, NotificationStatus
from sqlalchemy.exc import IntegrityError

def is_duplicate(session, dedup_key: str) -> bool:
    """Return True if a notification with this dedup_key already exists."""
    existing = session.exec(
        select(NotificationRecord).where(
            NotificationRecord.dedup_key == dedup_key
        )
    ).first()

    return existing is not None
def send_notification(notification: Notification, deliver_action=None) -> Notification:
    """Try to send a notification.

    If a notification with the same dedup_key was already sent, skip it and return it with status=SKIPPED.
    Otherwise, mark it SENT, store it, and return it.
    """
    db_service = DatabaseService() 
    with db_service.get_session_maker() as session:

        if is_duplicate(session, notification.dedup_key):
            notification.status = NotificationStatus.SKIPPED
            return notification


        if deliver_action is not None:
            deliver_action(notification)

        notification.status = NotificationStatus.SENT

        record = NotificationRecord(
        dedup_key=notification.dedup_key,
        recipient_id=notification.recipient_id,
        type=notification.type,
        status=NotificationStatus.SENT,
        title=notification.payload.title,
        body=notification.payload.body,
        metadata_json=json.dumps(notification.payload.metadata)    
        )
        try:
            session.add(record)
            session.commit()
            session.refresh(record)
    
        except(IntegrityError):
            session.rollback()
            notification.status = NotificationStatus.SKIPPED
    
        return notification


