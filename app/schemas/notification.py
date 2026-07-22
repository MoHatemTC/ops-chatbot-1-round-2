"""Notification model."""

from pydantic import BaseModel
from enum import Enum
from datetime import datetime, timezone
from pydantic import Field


class NotificationType(str, Enum):
    """Enum for notification type .

    To know whether it is for a session , dealine and so on as data required for each type is different.
    """

    SESSION_REMINDER = "session_reminder"
    DEADLINE_REMINDER = "deadline_reminder"
    AT_RISK_NUDGE = "at_risk_nudge"
    FEEDBACK_FOLLOWUP = "feedback_followup"


class NotificationStatus(str, Enum):
    """Enum for notification status.

    To know in what status is the notification skipped => when found notification already exists so no  need to resend it (prevents duplicates).
    """

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class NotificationPayload(BaseModel):
    """Payloads => content of the notification."""

    title: str
    body: str
    metadata: dict = Field(default_factory=dict)


class Notification(BaseModel):
    """A single notification instance uniquely identified by the dedup_key.

    To prevent duplicate delivery across job retries or re-runs.
    """

    recipient_id: str
    type: NotificationType
    payload: NotificationPayload
    dedup_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: NotificationStatus = NotificationStatus.PENDING
