"""Idempotent notification delivery service — prevents duplicate sends by dedup_key."""

import json
from typing import Optional

from sqlmodel import select
from sqlalchemy.exc import IntegrityError

from app.services.database import DatabaseService
from app.models.notification import NotificationRecord
from app.schemas.notification import Notification, NotificationStatus


def is_duplicate(session, dedup_key: str) -> bool:
    """Return True if a notification with this dedup_key was already SENT."""
    existing = get_existing_record(session, dedup_key)
    return existing is not None and existing.status == NotificationStatus.SENT


def get_existing_record(session, dedup_key: str) -> Optional[NotificationRecord]:
    """Return the existing NotificationRecord for this dedup_key, if any."""
    return session.exec(select(NotificationRecord).where(NotificationRecord.dedup_key == dedup_key)).first()


def send_notification(notification: Notification, deliver_action=None) -> Notification:
    """Try to send a notification, reserving the dedup_key before delivery.

    Reserves the dedup_key by inserting a PENDING record first. If a record
    already exists and was already SENT, this is a true duplicate — skip it.
    If a record exists but is still PENDING or FAILED (e.g. a retry of this
    same job), reuse that record instead of treating it as a duplicate.
    Only after delivery succeeds is the record marked SENT.
    """
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        record = get_existing_record(session, notification.dedup_key)

        if record is not None:
            if record.status == NotificationStatus.SENT:
                notification.status = NotificationStatus.SKIPPED
                return notification
            # PENDING or FAILED from an earlier attempt of this same job — reuse it.
        else:
            record = NotificationRecord(
                dedup_key=notification.dedup_key,
                recipient_id=notification.recipient_id,
                type=notification.type,
                status=NotificationStatus.PENDING,
                title=notification.payload.title,
                body=notification.payload.body,
                metadata_json=json.dumps(notification.payload.metadata),
            )
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
            except IntegrityError:
                # Someone else's insert won the race between our check and our insert.
                session.rollback()
                existing = get_existing_record(session, notification.dedup_key)
                if existing is not None and existing.status == NotificationStatus.SENT:
                    notification.status = NotificationStatus.SKIPPED
                    return notification
                record = existing

        if deliver_action is not None:
            deliver_action(notification)  # if this raises, propagate — tenacity needs to see it

        notification.status = NotificationStatus.SENT
        record.status = NotificationStatus.SENT
        session.add(record)
        session.commit()
        session.refresh(record)

        return notification
