class AtRiskSignals(BaseModel):
    missed_deadlines: bool
    inactive: bool
    low_progress: bool
    low_feedback: bool

    score: int

    at_risk: bool
class RiskThresholds(BaseModel):
    missed_deadlines: int = 2

    inactivity_days: int = 7

    minimum_progress_percent: float = 50

    minimum_feedback_score: float = 3
  def compute_risk_signals(
    progress: LearnerProgress,
    thresholds: RiskThresholds,
) -> AtRiskSignals:
  missed = progress.missed_deadlines >= thresholds.missed_deadlines
  score = sum(
    [
        missed,
        inactive,
        low_progress,
        low_feedback,
    ]
)
  at_risk = score > 0
