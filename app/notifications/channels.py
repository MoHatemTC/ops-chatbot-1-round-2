"""Ops notification channels with retry mechanism via tenacity."""

import logging
from typing import Any, Dict
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class ChannelDeliveryError(Exception):
    """Raised when notification delivery to an Ops channel fails."""

    pass


class BaseNotificationChannel:
    """Base interface for delivery channels."""

    name: str = "base"

    def send(self, payload: Dict[str, Any]) -> bool:
        """Send a notification payload."""
        raise NotImplementedError


class OpsSlackChannel(BaseNotificationChannel):
    """Slack notification channel for Ops ticket alerts."""

    name: str = "slack"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(ChannelDeliveryError),
        reraise=True,
    )
    def send(self, payload: Dict[str, Any]) -> bool:
        """Send notification payload to Slack with automatic retries."""
        ticket_id = payload.get("ticket_id")
        if payload.get("force_fail"):
            logger.warning("Simulating delivery failure for ticket %s", ticket_id)
            raise ChannelDeliveryError(f"HTTP 500: Failed to deliver to Slack for ticket {ticket_id}")

        logger.info("Successfully delivered Ops notification for ticket %s", ticket_id)
        return True
