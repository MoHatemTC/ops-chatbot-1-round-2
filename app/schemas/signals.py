"""At-risk signal computation: pure threshold evaluation of a LearnerProgress snapshot (PRD F2.3).

Deliberately free of I/O and side effects -- app.atrisk.detector calls this
once per learner and wraps the result in a DetectionResult. Being a pure
function of (progress, thresholds) is what lets the detector (and the
scheduled job built on top of it) be re-run safely: the same inputs always
produce the same signals.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.progress import LearnerProgress


class AtRiskSignals(BaseModel):
    """Individual risk indicators for one learner, plus the aggregate verdict."""

    missed_deadlines: bool
    inactive: bool
    low_progress: bool
    low_feedback: bool

    score: int
    at_risk: bool


class RiskThresholds(BaseModel):
    """Configurable thresholds a learner's progress is evaluated against."""

    missed_deadlines: int = 2
    inactivity_days: int = 7
    minimum_progress_percent: float = 50
    minimum_feedback_score: float = 3


def compute_risk_signals(
    progress: LearnerProgress,
    thresholds: RiskThresholds,
) -> AtRiskSignals:
    """Evaluate one learner's progress snapshot against the given thresholds.

    Each indicator is independent; `score` is how many tripped (0-4), and
    `at_risk` is True as soon as any one of them trips. A learner who
    hasn't left feedback yet (`feedback_score is None`) is never penalized
    for `low_feedback` -- that's "no signal," not a bad score.

    Args:
        progress: The learner's progress snapshot to evaluate.
        thresholds: The thresholds to evaluate it against.

    Returns:
        AtRiskSignals with each indicator plus the aggregate score/verdict.
    """
    missed = progress.missed_deadlines >= thresholds.missed_deadlines
    inactive = progress.inactive_days >= thresholds.inactivity_days
    low_progress = progress.progress_percent < thresholds.minimum_progress_percent
    low_feedback = progress.feedback_score is not None and progress.feedback_score < thresholds.minimum_feedback_score

    score = sum([missed, inactive, low_progress, low_feedback])
    at_risk = score > 0

    return AtRiskSignals(
        missed_deadlines=missed,
        inactive=inactive,
        low_progress=low_progress,
        low_feedback=low_feedback,
        score=score,
        at_risk=at_risk,
    )
