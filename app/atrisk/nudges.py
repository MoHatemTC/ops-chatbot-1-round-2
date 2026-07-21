"""Proactive at-risk nudge delivery — deduplicated, frequency-capped (PRD F2.4).

Defines an abstract NotificationSender contract so nudge delivery is
decoupled from any specific channel (email/SMS/push/in-app — whichever the
team picks). This keeps the deduplication logic testable in isolation: the
tests substitute an in-memory fake sender instead of hitting a real
provider (per Sarah's suggestion in the team thread).

Actual delivery reuses the existing idempotent notification service
(app.scheduler.runner.run_notification -> app.notifications.service), so
at-risk nudges get the same dedup_key + tenacity retry guarantees that
session/deadline reminders already rely on — no new delivery machinery to
trust.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from app.atrisk.detector import DetectionResult
from app.scheduler.runner import run_notification
from app.schemas.notification import Notification, NotificationPayload, NotificationType

# F2.4: frequency cap — don't nudge the same learner more than once per this many days.
NUDGE_FREQUENCY_DAYS_DEFAULT = 7


class NotificationSender(ABC):
    """Abstract contract for delivering a single notification through some channel.

    Kept decoupled from the at-risk detection/dedup logic so tests can
    substitute a fake sender instead of a real email/push/SMS provider.
    """

    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Deliver one notification. Raise on failure — the caller retries with backoff."""
        raise NotImplementedError


class NoOpNotificationSender(NotificationSender):
    """Default sender used when no real channel has been wired up yet.

    Delivers nothing externally but still goes through the full
    dedup/persist/retry path, so the job is safe to run before the actual
    notification lane (email/SMS/push) is chosen. Swap in a real sender via
    the `sender` argument on `send_at_risk_nudges` / `run_at_risk_job` once
    F2.1/F2.2's delivery channel is decided.
    """

    def send(self, notification: Notification) -> None:
        return None


class InMemoryNotificationSender(NotificationSender):
    """Test/dev sender that records every notification actually delivered.

    Used by evals/atrisk_suite.py and tests/test_atrisk.py to assert on
    deduplication without depending on a real notification channel.
    """

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)


def _nudge_period_bucket(evaluated_at: date, frequency_days: int) -> int:
    """Bucket a date into a period index of `frequency_days` length.

    Two evaluations that fall in the same bucket produce the same
    dedup_key for a given learner, which is how the frequency cap rides on
    the existing dedup_key/is_duplicate machinery instead of needing a
    separate "when did we last nudge this learner" lookup.

    Known limitation: because buckets are aligned to the epoch rather than
    to each learner's first nudge, two nudges can land as little as one day
    apart if they fall on either side of a bucket boundary — this guarantees
    "at most one nudge per `frequency_days`-day bucket," not a strict
    rolling "at least `frequency_days` days since the last nudge." If a
    strict rolling gap is required, replace this with a query against the
    learner's most recent SENT AT_RISK_NUDGE notification instead.
    """
    return evaluated_at.toordinal() // frequency_days


def build_nudge(
    result: DetectionResult,
    *,
    frequency_days: int = NUDGE_FREQUENCY_DAYS_DEFAULT,
) -> Notification:
    """Build the deduplicated Notification for one at-risk detection result.

    dedup_key encodes the learner, the notification type, and the
    frequency-cap bucket — so the same learner staying at_risk across
    daily detector runs within the cap window produces the SAME dedup_key,
    and is skipped as a duplicate by app.notifications.service instead of
    being re-nudged every single day.

    Args:
        result: The (at-risk) detection result to build a nudge for.
        frequency_days: Width of the frequency-cap window, in days.

    Returns:
        A Notification ready to hand to app.scheduler.runner.run_notification.
    """
    bucket = _nudge_period_bucket(result.evaluated_at.date(), frequency_days)
    dedup_key = f"atrisk:{result.learner_id}:nudge:{bucket}"
    return Notification(
        recipient_id=result.learner_id,
        type=NotificationType.AT_RISK_NUDGE,
        dedup_key=dedup_key,
        payload=NotificationPayload(
            title="Just checking in",
            body=(
                "We noticed things might be a little tough right now — no judgment at all. "
                "Reach out any time if you'd like a hand getting back on track."
            ),
            metadata={
                "score": result.signals.score,
                "missed_deadlines": result.signals.missed_deadlines,
                "inactive": result.signals.inactive,
                "low_progress": result.signals.low_progress,
                "low_feedback": result.signals.low_feedback,
            },
        ),
    )


def send_at_risk_nudges(
    results: list[DetectionResult],
    *,
    sender: Optional[NotificationSender] = None,
    frequency_days: int = NUDGE_FREQUENCY_DAYS_DEFAULT,
) -> list[Notification]:
    """Send deduplicated, frequency-capped nudges for every at-risk result.

    Only DetectionResults with signals.at_risk=True produce a nudge.
    Delivery goes through the existing idempotent notification service +
    tenacity retry (app.scheduler.runner.run_notification): a duplicate
    dedup_key within the frequency window is skipped rather than resent,
    and a failed delivery is retried with backoff before being marked
    FAILED instead of crashing the batch.

    Args:
        results: Detection results from app.atrisk.detector.run_detector.
        sender: NotificationSender used to actually deliver the nudge.
            Defaults to NoOpNotificationSender.
        frequency_days: Width of the frequency-cap window, in days.

    Returns:
        One Notification (with its final status) per at-risk result. Not
        at-risk results are skipped entirely and produce no entry.
    """
    active_sender = sender or NoOpNotificationSender()
    outcomes: list[Notification] = []
    for result in results:
        if not result.signals.at_risk:
            continue
        notification = build_nudge(result, frequency_days=frequency_days)
        outcomes.append(run_notification(notification, deliver_fn=active_sender.send))
    return outcomes
