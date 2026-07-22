"""Ops ticket notification delivery service with idempotency and retry mechanics."""

import json
import logging
from typing import Callable, Optional
from sqlmodel import select
from sqlalchemy.exc import IntegrityError

from app.services.database import DatabaseService
from app.models.notification import NotificationRecord
from app.schemas.notification import Notification, NotificationStatus
from app.notifications.channels import BaseNotificationChannel, OpsSlackChannel

logger = logging.getLogger(__name__)


def is_duplicate(session, dedup_key: str) -> bool:
    """Return True if a notification with this dedup_key was already SENT."""
    existing = get_existing_record(session, dedup_key)
    return existing is not None and existing.status == NotificationStatus.SENT


def get_existing_record(session, dedup_key: str) -> Optional[NotificationRecord]:
    """Return the existing NotificationRecord for this dedup_key, if any."""
    return session.exec(select(NotificationRecord).where(NotificationRecord.dedup_key == dedup_key)).first()


def send_notification(
    notification: Notification,
    deliver_action: Optional[Callable[[Notification], None]] = None,
) -> Notification:
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

        # Type guard للـ Pyright عشان يتأكد إن الكائن مش None ومستحيل يضرب
        if record is None:
            notification.status = NotificationStatus.FAILED
            return notification

        if deliver_action is not None:
            try:
                deliver_action(notification)
            except Exception as exc:
                record.status = NotificationStatus.FAILED
                session.add(record)
                session.commit()
                raise exc

        notification.status = NotificationStatus.SENT
        record.status = NotificationStatus.SENT
        session.add(record)
        session.commit()
        session.refresh(record)

        return notification


class OpsNotificationService:
    """End-to-end Notification Delivery Service for Ops team tickets."""

    def __init__(self, channel: Optional[BaseNotificationChannel] = None) -> None:
        """Initialize OpsNotificationService with a specific delivery channel."""
        self.channel = channel or OpsSlackChannel()

    def notify_new_ticket(self, notification: Notification) -> Notification:
        """Deliver a 'new ticket' notification using the idempotent delivery mechanism."""

        def action(notif: Notification) -> None:
            payload = {
                "ticket_id": notif.payload.metadata.get("ticket_id"),
                "title": notif.payload.title,
                "body": notif.payload.body,
                "force_fail": notif.payload.metadata.get("force_fail", False),
            }
            self.channel.send(payload)

        return send_notification(notification, deliver_action=action)
