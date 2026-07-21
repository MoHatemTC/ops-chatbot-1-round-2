"""Tests for the at-risk detector, state persistence, nudges, and scheduled job.

Follows the conventions in tests/test_scheduler_scaffold.py: DB-backed tests
clean up their own tables via an autouse fixture and run against the
project's configured Postgres (see docs/database.md and .env.test).
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete
from sqlmodel import select

from app.atrisk.detector import detect_at_risk, resolve_thresholds, run_detector
from app.atrisk.nudges import InMemoryNotificationSender, build_nudge, send_at_risk_nudges
from app.atrisk.state import AtRiskStateRecord, get_aggregate, upsert_at_risk_state
from app.jobs.atrisk_job import run_at_risk_job
from app.models.notification import NotificationRecord
from app.schemas.notification import NotificationStatus
from app.schemas.progress import LearnerProgress
from app.schemas.signals import RiskThresholds
from app.services.database import DatabaseService


def _progress(learner_id: str, **kwargs) -> LearnerProgress:
    return LearnerProgress(learner_id=learner_id, evaluated_at=datetime.now(UTC), **kwargs)


@pytest.fixture(autouse=True)
def reset_atrisk_tables():
    """Clear at-risk state + notification records before each test."""
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        session.exec(delete(AtRiskStateRecord))
        session.exec(delete(NotificationRecord))
        session.commit()


def test_detect_at_risk_flags_missed_deadlines():
    """Missing enough deadlines alone is enough to flag a learner at_risk."""
    progress = _progress("learner_1", missed_deadlines=2, inactive_days=0, progress_percent=100, feedback_score=5)
    result = detect_at_risk(progress)
    assert result.signals.at_risk is True
    assert result.signals.missed_deadlines is True
    assert result.signals.score == 1


def test_detect_at_risk_healthy_learner_not_flagged():
    """A learner with no tripped signals is never flagged at_risk."""
    progress = _progress("learner_2", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=5)
    result = detect_at_risk(progress)
    assert result.signals.at_risk is False
    assert result.signals.score == 0


def test_no_feedback_yet_does_not_count_as_low_feedback():
    """A learner who hasn't left a feedback score yet shouldn't be penalized for it."""
    progress = _progress("learner_no_fb", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=None)
    result = detect_at_risk(progress)
    assert result.signals.low_feedback is False
    assert result.signals.at_risk is False


def test_resolve_thresholds_per_learner_override():
    """Per-learner threshold overrides make evaluation configurable per learner."""
    strict = RiskThresholds(missed_deadlines=1)
    resolved_default = resolve_thresholds("learner_x")
    resolved_override = resolve_thresholds("learner_x", overrides={"learner_x": strict})
    assert resolved_default.missed_deadlines != resolved_override.missed_deadlines
    assert resolved_override.missed_deadlines == 1


def test_run_detector_is_pure_and_deterministic():
    """Running the detector twice on the same input yields identical signals — required for job idempotency."""
    progress = _progress("learner_3", missed_deadlines=3, inactive_days=8, progress_percent=20, feedback_score=1)
    first = run_detector([progress])[0]
    second = run_detector([progress])[0]
    assert first.signals == second.signals


def test_upsert_at_risk_state_is_idempotent_for_same_day():
    """Re-persisting the same learner+day updates the one row instead of duplicating it."""
    run_date = date(2026, 7, 20)
    progress = _progress("learner_idem", missed_deadlines=5, inactive_days=0, progress_percent=100, feedback_score=5)
    result = detect_at_risk(progress)

    upsert_at_risk_state(result, run_date=run_date)
    upsert_at_risk_state(result, run_date=run_date)  # simulate a job re-run / retry

    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        rows = session.exec(
            select(AtRiskStateRecord).where(
                AtRiskStateRecord.learner_id == "learner_idem",
                AtRiskStateRecord.run_date == run_date,
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].at_risk is True


def test_get_aggregate_reflects_persisted_state():
    """Aggregates read back exactly what was persisted for the day."""
    run_date = date(2026, 7, 21)
    at_risk_progress = _progress(
        "learner_agg_1", missed_deadlines=5, inactive_days=0, progress_percent=100, feedback_score=5
    )
    healthy_progress = _progress(
        "learner_agg_2", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=5
    )

    upsert_at_risk_state(detect_at_risk(at_risk_progress), run_date=run_date)
    upsert_at_risk_state(detect_at_risk(healthy_progress), run_date=run_date)

    aggregate = get_aggregate(run_date)
    assert aggregate.total_learners == 2
    assert aggregate.at_risk_count == 1
    assert aggregate.at_risk_percent == 50.0


def test_build_nudge_dedup_key_stable_within_frequency_window():
    """Two evaluations of the same learner within the frequency-cap window produce the same dedup_key."""
    progress = _progress("learner_nudge", missed_deadlines=5, inactive_days=0, progress_percent=100, feedback_score=5)
    result_a = detect_at_risk(progress)
    result_b = detect_at_risk(progress)
    assert build_nudge(result_a).dedup_key == build_nudge(result_b).dedup_key


def test_send_at_risk_nudges_skips_learners_who_are_not_at_risk():
    """Only at-risk learners get a nudge attempt at all."""
    at_risk_progress = _progress(
        "learner_send_1", missed_deadlines=5, inactive_days=0, progress_percent=100, feedback_score=5
    )
    healthy_progress = _progress(
        "learner_send_2", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=5
    )

    results = run_detector([at_risk_progress, healthy_progress])
    sender = InMemoryNotificationSender()
    outcomes = send_at_risk_nudges(results, sender=sender)

    assert len(outcomes) == 1
    assert outcomes[0].recipient_id == "learner_send_1"
    assert outcomes[0].status == NotificationStatus.SENT
    assert len(sender.sent) == 1


def test_send_at_risk_nudges_deduplicates_across_reruns():
    """Running nudge delivery twice for the same at-risk learner+window sends only once."""
    progress = _progress("learner_dedupe", missed_deadlines=5, inactive_days=0, progress_percent=100, feedback_score=5)
    results = run_detector([progress])
    sender = InMemoryNotificationSender()

    first_run = send_at_risk_nudges(results, sender=sender)
    second_run = send_at_risk_nudges(results, sender=sender)  # simulate the job re-running

    assert first_run[0].status == NotificationStatus.SENT
    assert second_run[0].status == NotificationStatus.SKIPPED
    assert len(sender.sent) == 1  # the underlying channel was only actually invoked once


def test_run_at_risk_job_end_to_end_idempotent():
    """The full job -- detect, persist, nudge -- is safe to run twice for the same day."""
    run_date = date(2026, 7, 22)
    progress_list = [
        _progress("learner_job_1", missed_deadlines=5, inactive_days=0, progress_percent=100, feedback_score=5),
        _progress("learner_job_2", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=5),
    ]
    sender = InMemoryNotificationSender()

    first = run_at_risk_job(lambda: progress_list, sender=sender, run_date=run_date)
    second = run_at_risk_job(lambda: progress_list, sender=sender, run_date=run_date)

    assert first.evaluated_count == 2
    assert first.at_risk_count == 1
    assert second.at_risk_count == 1
    assert len(sender.sent) == 1  # nudge only actually delivered once across both runs

    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        rows = session.exec(select(AtRiskStateRecord).where(AtRiskStateRecord.run_date == run_date)).all()
    assert len(rows) == 2  # not duplicated by the second run
