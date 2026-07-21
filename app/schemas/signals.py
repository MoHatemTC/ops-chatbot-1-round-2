"""At-risk signal computation for learners (PRD F2.3).

This module was a broken Week-1 draft (syntax errors: missing imports, bad
indentation, an incomplete function body with undefined names, and no
return statement). It has been fixed here because app/atrisk/detector.py
depends on it directly — the detector cannot import a module that doesn't
parse.
"""

from pydantic import BaseModel

from app.schemas.progress import LearnerProgress


class AtRiskSignals(BaseModel):
    """Which individual risk signals fired for a learner, plus the overall verdict."""

    missed_deadlines: bool
    inactive: bool
    low_progress: bool
    low_feedback: bool

    score: int
    at_risk: bool


class RiskThresholds(BaseModel):
    """Configurable thresholds used to evaluate at-risk signals."""

    missed_deadlines: int = 2
    inactivity_days: int = 7
    minimum_progress_percent: float = 50
    minimum_feedback_score: float = 3


def compute_risk_signals(
    progress: LearnerProgress,
    thresholds: RiskThresholds,
) -> AtRiskSignals:
    """Evaluate a learner's progress snapshot against configurable thresholds.

    Args:
        progress: The learner's latest progress snapshot.
        thresholds: The thresholds to evaluate against.

    Returns:
        AtRiskSignals with each individual signal, an integer score (count
        of tripped signals, 0-4), and an overall at_risk boolean (True if
        any signal tripped).
    """
    missed = progress.missed_deadlines >= thresholds.missed_deadlines
    inactive = progress.inactive_days >= thresholds.inactivity_days
    low_progress = progress.progress_percent < thresholds.minimum_progress_percent
    # No feedback yet is not the same as low feedback — don't penalize learners
    # who simply haven't left a score.
    low_feedback = (
        progress.feedback_score is not None and progress.feedback_score < thresholds.minimum_feedback_score
    )

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
