"""Database model for storing sent/skipped notifications, enforcing dedup_key uniqueness."""
from sqlmodel import Field
from app.models.base import BaseModel
from app.schemas.notification import NotificationType, NotificationStatus


class NotificationRecord(BaseModel, table=True):
    """Database record of a notification delivery attempt.

    Attributes:
        id: The primary key.
        dedup_key: Unique fingerprint preventing duplicate delivery.
        recipient_id: Learner this notification is for.
        type: What kind of notification this is.
        status: Current delivery status.
        title: Notification title.
        body: Notification body text.
        metadata_json: Arbitrary extra data, JSON-encoded.
        created_at: Inherited from BaseModel.
    """
    id: int = Field(default=None, primary_key=True)
    dedup_key: str = Field(unique=True, index=True)
    recipient_id: str
    type: NotificationType
    status: NotificationStatus = NotificationStatus.PENDING
    title: str
    body: str
    metadata_json: str = "{}"
