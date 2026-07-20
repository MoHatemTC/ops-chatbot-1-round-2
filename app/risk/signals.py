from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.progress import LearnerProgress


class RiskIndicator(str, Enum):
    MISSED_DEADLINES = "missed_deadlines"
    INACTIVITY = "inactivity"
    LOW_PROGRESS = "low_progress"
    LOW_FEEDBACK = "low_feedback"


class RiskThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_missed_deadlines: int = 2
    max_inactive_days: int = 7
    min_progress_ratio: float = 0.25
    min_feedback_rating: float = 2.5


class AtRiskSignal(BaseModel):
    learner_id: str
    cohort_id: str
    triggered_indicators: List[RiskIndicator]
    is_at_risk: bool

    @property
    def indicators(self) -> List[RiskIndicator]:
        return self.triggered_indicators


def compute_signal(progress: LearnerProgress, thresholds: Optional[RiskThresholds] = None) -> AtRiskSignal:
    t = thresholds or RiskThresholds()
    indicators: List[RiskIndicator] = []

    if progress.missed_deadlines > t.max_missed_deadlines:
        indicators.append(RiskIndicator.MISSED_DEADLINES)

    days_inactive = progress.days_inactive
    if days_inactive is not None and days_inactive > t.max_inactive_days:
        indicators.append(RiskIndicator.INACTIVITY)

    if progress.progress_ratio < t.min_progress_ratio:
        indicators.append(RiskIndicator.LOW_PROGRESS)

    if progress.average_feedback_score is not None and progress.average_feedback_score < t.min_feedback_rating:
        indicators.append(RiskIndicator.LOW_FEEDBACK)

    return AtRiskSignal(
        learner_id=progress.learner_id,
        cohort_id=progress.cohort_id,
        triggered_indicators=indicators,
        is_at_risk=len(indicators) > 0,
    )


def compute_signals(
    progress_list: List[LearnerProgress], thresholds: Optional[RiskThresholds] = None
) -> List[AtRiskSignal]:
    return [compute_signal(p, thresholds) for p in progress_list]
