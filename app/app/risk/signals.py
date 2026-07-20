from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class RiskIndicator(BaseModel):
    name: str
    score: float


class RiskThresholds(BaseModel):
    warning: float = 0.5
    critical: float = 0.8


class AtRiskSignal(BaseModel):
    is_at_risk: bool
    risk_level: str
    indicators: List[RiskIndicator] = []
    evaluated_at: Optional[datetime] = None


def compute_signal(indicator: RiskIndicator, thresholds: RiskThresholds) -> AtRiskSignal:
    level = "normal"
    at_risk = False
    if indicator.score >= thresholds.critical:
        level = "critical"
        at_risk = True
    elif indicator.score >= thresholds.warning:
        level = "warning"
        at_risk = True

    return AtRiskSignal(is_at_risk=at_risk, risk_level=level, indicators=[indicator])


def compute_signals(indicators: List[RiskIndicator], thresholds: RiskThresholds) -> AtRiskSignal:
    max_score = max([i.score for i in indicators], default=0.0)
    dummy_indicator = RiskIndicator(name="max_risk", score=max_score)
    return compute_signal(dummy_indicator, thresholds)
