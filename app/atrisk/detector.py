"""At-risk detector: evaluates configurable thresholds per learner (PRD F2.3).

This module is the pure evaluation step — no DB or notification calls here.
Given progress snapshots and thresholds (optionally overridden per learner),
it produces a DetectionResult per learner. app/atrisk/state.py persists
those results as an auditable record, and app/atrisk/nudges.py acts on
them. Keeping this layer pure (no I/O, deterministic given its inputs) is
what makes the scheduled job in app/jobs/atrisk_job.py safe to re-run:
detection itself can never be the source of a duplicate side effect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Mapping, Optional

from pydantic import BaseModel

from app.schemas.progress import LearnerProgress
from app.schemas.signals import AtRiskSignals, RiskThresholds, compute_risk_signals

DEFAULT_THRESHOLDS = RiskThresholds()


class DetectionResult(BaseModel):
    """Outcome of evaluating one learner's progress snapshot against thresholds."""

    learner_id: str
    signals: AtRiskSignals
    thresholds: RiskThresholds
    evaluated_at: datetime


def resolve_thresholds(
    learner_id: str,
    overrides: Optional[Mapping[str, RiskThresholds]] = None,
    default: RiskThresholds = DEFAULT_THRESHOLDS,
) -> RiskThresholds:
    """Resolve the thresholds to use for one learner.

    Per-learner overrides (e.g. a cohort-specific policy) take precedence
    over the default thresholds. This is what makes threshold evaluation
    "configurable per learner" rather than a single hardcoded global cutoff.

    Args:
        learner_id: The learner to resolve thresholds for.
        overrides: Optional mapping of learner_id -> RiskThresholds.
        default: Thresholds to fall back to when no override exists.

    Returns:
        The RiskThresholds to evaluate this learner against.
    """
    if overrides and learner_id in overrides:
        return overrides[learner_id]
    return default


def detect_at_risk(
    progress: LearnerProgress,
    *,
    thresholds: Optional[RiskThresholds] = None,
    overrides: Optional[Mapping[str, RiskThresholds]] = None,
) -> DetectionResult:
    """Evaluate a single learner's progress snapshot and return a DetectionResult.

    Args:
        progress: The learner's latest progress snapshot.
        thresholds: Explicit thresholds to use. Takes precedence over `overrides`.
        overrides: Per-learner threshold overrides, consulted when `thresholds`
            is not given (see `resolve_thresholds`).

    Returns:
        A DetectionResult capturing the signals, the thresholds actually
        used, and when the evaluation ran.
    """
    resolved = thresholds if thresholds is not None else resolve_thresholds(progress.learner_id, overrides)
    signals = compute_risk_signals(progress, resolved)
    return DetectionResult(
        learner_id=progress.learner_id,
        signals=signals,
        thresholds=resolved,
        evaluated_at=datetime.now(UTC),
    )


def run_detector(
    progress_snapshots: Iterable[LearnerProgress],
    *,
    threshold_overrides: Optional[Mapping[str, RiskThresholds]] = None,
) -> list[DetectionResult]:
    """Run the at-risk detector over a batch of learner progress snapshots.

    This is the pure evaluation step of the scheduled job — no I/O. The
    caller (app/jobs/atrisk_job.py) is responsible for sourcing progress
    snapshots and persisting/acting on the results. Being a pure function
    of its inputs, calling this twice with the same snapshots always
    produces identical results — the detector itself never needs a
    "have I already run today" check.

    Args:
        progress_snapshots: The learner progress snapshots to evaluate.
        threshold_overrides: Optional per-learner RiskThresholds overrides.

    Returns:
        One DetectionResult per input snapshot, in the same order.
    """
    return [detect_at_risk(progress, overrides=threshold_overrides) for progress in progress_snapshots]
