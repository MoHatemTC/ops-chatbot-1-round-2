"""Delivery log abstractions and models for Ops notifications."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from app.schemas.notification import NotificationStatus


class OpsDeliveryLog(BaseModel):
    """Delivery log schema representing audit records for Ops notifications."""

    dedup_key: str
    ticket_id: str
    channel: str
    status: NotificationStatus
    attempts: int = 1
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
