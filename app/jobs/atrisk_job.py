"""Scheduled at-risk detector job (PRD F2.3-F2.5): idempotent, retried with backoff.

Wires together:
  - a progress provider (source of LearnerProgress snapshots — pluggable,
    since where progress data comes from is outside this job's scope)
  - app.atrisk.detector (pure threshold evaluation)
  - app.atrisk.state (auditable persistence + dashboard aggregates)
  - app.atrisk.nudges (deduplicated, frequency-capped proactive notifications)

Idempotency: re-running this job for the same UTC calendar day is always
safe.
  - Detection is a pure function of its inputs (no side effects).
  - State persistence upserts by (learner_id, run_date) instead of
    inserting new rows (app.atrisk.state.upsert_at_risk_state).
  - Nudge delivery is deduplicated by a dedup_key bucketed on the
    frequency-cap window (app.atrisk.nudges.build_nudge).

So retries, manual re-runs, and job-scheduler double-fires never produce
duplicate state rows or duplicate learner-facing messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Mapping, Optional, Protocol

from tenacity import retry, stop_after_attempt, wait_exponential

from app.atrisk.detector import DetectionResult, run_detector
from app.atrisk.nudges import NoOpNotificationSender, NotificationSender, send_at_risk_nudges
from app.atrisk.state import AtRiskAggregate, get_aggregate, upsert_at_risk_state
from app.core.logging import logger
from app.schemas.notification import NotificationStatus
from app.schemas.progress import LearnerProgress
from app.schemas.signals import RiskThresholds


class ProgressProvider(Protocol):
    """Supplies the learner progress snapshots the detector runs against.

    Deliberately abstract: this job doesn't own how progress data is
    computed or sourced (that may be a DB query, a call to another
    service, a CSV import, etc.) — only that it can be asked for a list of
    snapshots. Inject a real provider when wiring this job into a
    scheduler; tests inject a static list.
    """

    def __call__(self) -> list[LearnerProgress]: ...


@dataclass
class AtRiskJobResult:
    """Summary of one job run — useful for logging/monitoring and for tests."""

    run_date: date
    evaluated_count: int
    at_risk_count: int
    nudges_sent: int
    detections: list[DetectionResult]
    aggregate: AtRiskAggregate


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def _persist_with_retry(result: DetectionResult, run_date: date):
    """Persist one learner's detection result, retrying transient DB errors with backoff."""
    return upsert_at_risk_state(result, run_date=run_date)


def run_at_risk_job(
    progress_provider: ProgressProvider,
    *,
    threshold_overrides: Optional[Mapping[str, RiskThresholds]] = None,
    sender: Optional[NotificationSender] = None,
    run_date: Optional[date] = None,
) -> AtRiskJobResult:
    """Run the full at-risk detector job once: detect -> persist -> nudge.

    Args:
        progress_provider: Callable returning the LearnerProgress snapshots
            to evaluate this run.
        threshold_overrides: Optional per-learner RiskThresholds overrides.
        sender: NotificationSender used to deliver nudges. Defaults to a
            no-op sender so the job never crashes for lack of a configured
            channel — wire in the real channel once the notification lane
            is chosen.
        run_date: Overrides "today" (UTC). Mainly for deterministic tests
            and for manually backfilling a specific day.

    Returns:
        AtRiskJobResult summarizing what happened this run.
    """
    effective_run_date = run_date or datetime.now(UTC).date()
    logger.info("atrisk_job_started", run_date=str(effective_run_date))

    progress_snapshots = list(progress_provider())
    detections = run_detector(progress_snapshots, threshold_overrides=threshold_overrides)

    for result in detections:
        try:
            _persist_with_retry(result, effective_run_date)
        except Exception as exc:  # noqa: BLE001 -- one learner's persistence failure shouldn't sink the batch
            logger.error(
                "atrisk_state_persist_failed",
                learner_id=result.learner_id,
                run_date=str(effective_run_date),
                error=str(exc),
            )

    nudge_outcomes = send_at_risk_nudges(detections, sender=sender or NoOpNotificationSender())
    aggregate = get_aggregate(effective_run_date)

    summary = AtRiskJobResult(
        run_date=effective_run_date,
        evaluated_count=len(detections),
        at_risk_count=sum(1 for d in detections if d.signals.at_risk),
        nudges_sent=sum(1 for n in nudge_outcomes if n.status == NotificationStatus.SENT),
        detections=detections,
        aggregate=aggregate,
    )

    logger.info(
        "atrisk_job_completed",
        run_date=str(effective_run_date),
        evaluated_count=summary.evaluated_count,
        at_risk_count=summary.at_risk_count,
        nudges_sent=summary.nudges_sent,
    )
    return summary


def _no_progress_configured() -> list[LearnerProgress]:
    """Placeholder progress provider used when running this module directly.

    No progress-data source is wired up in this deliverable — plug in a
    real provider (e.g. a DB query, or a call to whatever service computes
    LearnerProgress) before scheduling this job for real.
    """
    logger.warning("atrisk_job_no_progress_provider_configured")
    return []


if __name__ == "__main__":
    run_at_risk_job(progress_provider=_no_progress_configured)
