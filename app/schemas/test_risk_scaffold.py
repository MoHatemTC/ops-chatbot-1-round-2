"""Tests for the at-risk signal detection scaffold (F2.3-F2.5 kickoff).

Covers: LearnerProgress computed fields, each individual risk indicator
in isolation, combinations of indicators, threshold-boundary behavior,
and batch computation via ``compute_signals``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.risk.signals import (
    AtRiskSignal,
    RiskIndicator,
    RiskThresholds,
    compute_signal,
    compute_signals,
)
from app.schemas.progress import FeedbackEntry, LearnerProgress

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def make_progress(**overrides) -> LearnerProgress:
    """Build a healthy baseline LearnerProgress, overridden per-test."""
    defaults = dict(
        learner_id="learner-1",
        cohort_id="cohort-a",
        as_of=NOW,
        total_tasks=10,
        completed_tasks=8,
        missed_deadlines=0,
        last_active_at=NOW - timedelta(days=1),
        recent_feedback=[FeedbackEntry(score=4.0, submitted_at=NOW - timedelta(days=1))],
    )
    defaults.update(overrides)
    return LearnerProgress(**defaults)


@pytest.fixture
def thresholds() -> RiskThresholds:
    """Default thresholds, constructed directly (bypassing env vars)."""
    return RiskThresholds(
        max_missed_deadlines=1,
        max_inactivity_days=5.0,
        min_progress_ratio=0.5,
        min_average_feedback=2.5,
    )


# --- LearnerProgress computed fields -----------------------------------------


class TestLearnerProgressComputedFields:
    def test_progress_ratio(self):
        progress = make_progress(total_tasks=4, completed_tasks=1)
        assert progress.progress_ratio == 0.25

    def test_progress_ratio_with_no_tasks_is_full(self):
        progress = make_progress(total_tasks=0, completed_tasks=0)
        assert progress.progress_ratio == 1.0

    def test_days_inactive_computed_from_as_of(self):
        progress = make_progress(last_active_at=NOW - timedelta(days=3))
        assert progress.days_inactive == pytest.approx(3.0)

    def test_days_inactive_none_when_never_active(self):
        progress = make_progress(last_active_at=None)
        assert progress.days_inactive is None

    def test_average_feedback_score(self):
        progress = make_progress(
            recent_feedback=[
                FeedbackEntry(score=3.0, submitted_at=NOW),
                FeedbackEntry(score=1.0, submitted_at=NOW),
            ]
        )
        assert progress.average_feedback_score == pytest.approx(2.0)

    def test_average_feedback_score_none_when_no_feedback(self):
        progress = make_progress(recent_feedback=[])
        assert progress.average_feedback_score is None

    def test_naive_datetimes_normalized_to_utc(self):
        progress = make_progress(last_active_at=datetime(2026, 7, 10, 0, 0))
        assert progress.last_active_at.tzinfo is not None

    def test_completed_cannot_exceed_total(self):
        with pytest.raises(ValidationError):
            make_progress(total_tasks=2, completed_tasks=5)

    def test_feedback_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackEntry(score=6.0, submitted_at=NOW)


# --- Individual risk indicators ------------------------------------------------


class TestIndividualIndicators:
    def test_no_indicators_for_healthy_learner(self, thresholds):
        signal = compute_signal(make_progress(), thresholds)
        assert signal.triggered_indicators == []
        assert signal.is_at_risk is False

    def test_missed_deadlines_triggers(self, thresholds):
        signal = compute_signal(make_progress(missed_deadlines=2), thresholds)
        assert RiskIndicator.MISSED_DEADLINES in signal.triggered_indicators

    def test_missed_deadlines_at_threshold_does_not_trigger(self, thresholds):
        signal = compute_signal(make_progress(missed_deadlines=1), thresholds)
        assert RiskIndicator.MISSED_DEADLINES not in signal.triggered_indicators

    def test_inactivity_triggers(self, thresholds):
        signal = compute_signal(
            make_progress(last_active_at=NOW - timedelta(days=10)), thresholds
        )
        assert RiskIndicator.INACTIVITY in signal.triggered_indicators

    def test_inactivity_at_threshold_does_not_trigger(self, thresholds):
        signal = compute_signal(
            make_progress(last_active_at=NOW - timedelta(days=5)), thresholds
        )
        assert RiskIndicator.INACTIVITY not in signal.triggered_indicators

    def test_never_active_does_not_trigger_inactivity(self, thresholds):
        """Absence of activity data should not be conflated with an idle learner."""
        signal = compute_signal(make_progress(last_active_at=None), thresholds)
        assert RiskIndicator.INACTIVITY not in signal.triggered_indicators

    def test_low_progress_triggers(self, thresholds):
        signal = compute_signal(
            make_progress(total_tasks=10, completed_tasks=2), thresholds
        )
        assert RiskIndicator.LOW_PROGRESS in signal.triggered_indicators

    def test_progress_at_threshold_does_not_trigger(self, thresholds):
        signal = compute_signal(
            make_progress(total_tasks=10, completed_tasks=5), thresholds
        )
        assert RiskIndicator.LOW_PROGRESS not in signal.triggered_indicators

    def test_low_feedback_triggers(self, thresholds):
        signal = compute_signal(
            make_progress(
                recent_feedback=[FeedbackEntry(score=1.0, submitted_at=NOW)]
            ),
            thresholds,
        )
        assert RiskIndicator.LOW_FEEDBACK in signal.triggered_indicators

    def test_no_feedback_does_not_trigger_low_feedback(self, thresholds):
        """Absence of feedback should not be conflated with negative feedback."""
        signal = compute_signal(make_progress(recent_feedback=[]), thresholds)
        assert RiskIndicator.LOW_FEEDBACK not in signal.triggered_indicators


# --- Combinations & overall status ---------------------------------------------


class TestCombinedSignals:
    def test_multiple_indicators_all_captured(self, thresholds):
        progress = make_progress(
            missed_deadlines=3,
            total_tasks=10,
            completed_tasks=1,
            last_active_at=NOW - timedelta(days=20),
            recent_feedback=[FeedbackEntry(score=0.5, submitted_at=NOW)],
        )
        signal = compute_signal(progress, thresholds)
        assert set(signal.triggered_indicators) == {
            RiskIndicator.MISSED_DEADLINES,
            RiskIndicator.INACTIVITY,
            RiskIndicator.LOW_PROGRESS,
            RiskIndicator.LOW_FEEDBACK,
        }
        assert signal.is_at_risk is True

    def test_signal_preserves_learner_and_cohort_identity(self, thresholds):
        progress = make_progress(learner_id="learner-42", cohort_id="cohort-z")
        signal = compute_signal(progress, thresholds)
        assert signal.learner_id == "learner-42"
        assert signal.cohort_id == "cohort-z"

    def test_default_thresholds_used_when_none_passed(self):
        """compute_signal should fall back to RiskThresholds() defaults."""
        signal = compute_signal(make_progress())
        assert isinstance(signal, AtRiskSignal)
        assert signal.is_at_risk is False


# --- Batch computation -----------------------------------------------------


class TestComputeSignalsBatch:
    def test_batch_matches_individual_computation(self, thresholds):
        healthy = make_progress(learner_id="l1")
        at_risk = make_progress(learner_id="l2", missed_deadlines=5)

        results = compute_signals([healthy, at_risk], thresholds)

        assert len(results) == 2
        assert results[0].learner_id == "l1"
        assert results[0].is_at_risk is False
        assert results[1].learner_id == "l2"
        assert results[1].is_at_risk is True

    def test_batch_empty_input(self, thresholds):
        assert compute_signals([], thresholds) == []


# --- Threshold configuration ------------------------------------------------


class TestRiskThresholdsConfig:
    def test_thresholds_are_overridable(self):
        strict = RiskThresholds(max_missed_deadlines=0)
        signal = compute_signal(make_progress(missed_deadlines=1), strict)
        assert RiskIndicator.MISSED_DEADLINES in signal.triggered_indicators

    def test_thresholds_are_frozen(self):
        strict = RiskThresholds()
        with pytest.raises(ValidationError):
            strict.max_missed_deadlines = 99
