"""Evaluation suite for the at-risk detector (PRD F2.3): reports precision.

Runs app.atrisk.detector against a small hand-labeled dataset of
LearnerProgress snapshots with known ground-truth at-risk labels, and
reports precision, recall, F1, and accuracy.

This is deliberately NOT an LLM-judge eval like evals/evaluator.py — the
detector is a deterministic rule evaluation, not a model generating free
text, so there's nothing for an LLM judge to score. Precision/recall
against a well-chosen label set should be 1.0; any drop signals a real bug
in the threshold logic, not judge variance.

Run directly:
    python -m evals.atrisk_suite
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

# Fix import path for app module (matches evals/main.py's convention)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.atrisk.detector import detect_at_risk  # noqa: E402
from app.core.logging import logger  # noqa: E402
from app.schemas.progress import LearnerProgress  # noqa: E402
from app.schemas.signals import RiskThresholds  # noqa: E402

THRESHOLDS = RiskThresholds()


@dataclass
class LabeledCase:
    """One labeled test case: a progress snapshot plus its expected verdict."""

    name: str
    progress: LearnerProgress
    expected_at_risk: bool
    expected_signals: dict = field(default_factory=dict)


def _progress(learner_id: str, **kwargs) -> LearnerProgress:
    return LearnerProgress(learner_id=learner_id, evaluated_at=datetime.now(UTC), **kwargs)


def build_labeled_dataset() -> list[LabeledCase]:
    """Hand-labeled cases covering each signal individually, combinations, and edge cases."""
    return [
        LabeledCase(
            name="healthy_learner",
            progress=_progress(
                "learner_healthy", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=5
            ),
            expected_at_risk=False,
            expected_signals={"missed_deadlines": False, "inactive": False, "low_progress": False, "low_feedback": False},
        ),
        LabeledCase(
            name="missed_deadlines_only",
            progress=_progress(
                "learner_missed",
                missed_deadlines=THRESHOLDS.missed_deadlines,
                inactive_days=0,
                progress_percent=100,
                feedback_score=5,
            ),
            expected_at_risk=True,
            expected_signals={"missed_deadlines": True, "inactive": False, "low_progress": False, "low_feedback": False},
        ),
        LabeledCase(
            name="inactive_only",
            progress=_progress(
                "learner_inactive",
                missed_deadlines=0,
                inactive_days=THRESHOLDS.inactivity_days,
                progress_percent=100,
                feedback_score=5,
            ),
            expected_at_risk=True,
            expected_signals={"missed_deadlines": False, "inactive": True, "low_progress": False, "low_feedback": False},
        ),
        LabeledCase(
            name="low_progress_only",
            progress=_progress(
                "learner_low_progress",
                missed_deadlines=0,
                inactive_days=0,
                progress_percent=THRESHOLDS.minimum_progress_percent - 1,
                feedback_score=5,
            ),
            expected_at_risk=True,
            expected_signals={"missed_deadlines": False, "inactive": False, "low_progress": True, "low_feedback": False},
        ),
        LabeledCase(
            name="low_feedback_only",
            progress=_progress(
                "learner_low_feedback",
                missed_deadlines=0,
                inactive_days=0,
                progress_percent=100,
                feedback_score=THRESHOLDS.minimum_feedback_score - 0.1,
            ),
            expected_at_risk=True,
            expected_signals={"missed_deadlines": False, "inactive": False, "low_progress": False, "low_feedback": True},
        ),
        LabeledCase(
            name="no_feedback_yet_is_not_low_feedback",
            progress=_progress(
                "learner_no_feedback", missed_deadlines=0, inactive_days=0, progress_percent=100, feedback_score=None
            ),
            expected_at_risk=False,
            expected_signals={"missed_deadlines": False, "inactive": False, "low_progress": False, "low_feedback": False},
        ),
        LabeledCase(
            name="all_signals_combined",
            progress=_progress(
                "learner_everything_wrong",
                missed_deadlines=THRESHOLDS.missed_deadlines + 3,
                inactive_days=THRESHOLDS.inactivity_days + 5,
                progress_percent=10,
                feedback_score=1,
            ),
            expected_at_risk=True,
            expected_signals={"missed_deadlines": True, "inactive": True, "low_progress": True, "low_feedback": True},
        ),
        LabeledCase(
            name="just_under_every_threshold",
            progress=_progress(
                "learner_borderline_safe",
                missed_deadlines=THRESHOLDS.missed_deadlines - 1,
                inactive_days=THRESHOLDS.inactivity_days - 1,
                progress_percent=THRESHOLDS.minimum_progress_percent,
                feedback_score=THRESHOLDS.minimum_feedback_score,
            ),
            expected_at_risk=False,
            expected_signals={"missed_deadlines": False, "inactive": False, "low_progress": False, "low_feedback": False},
        ),
    ]


def run_suite(cases: Optional[list[LabeledCase]] = None) -> dict:
    """Run the detector against every labeled case and compute precision/recall/F1/accuracy.

    Args:
        cases: Labeled cases to evaluate. Defaults to `build_labeled_dataset()`.

    Returns:
        A report dict: per-case results plus aggregate metrics.
    """
    cases = cases if cases is not None else build_labeled_dataset()

    tp = fp = tn = fn = 0
    case_results = []
    signal_mismatches = []

    for case in cases:
        result = detect_at_risk(case.progress, thresholds=THRESHOLDS)
        predicted = result.signals.at_risk
        expected = case.expected_at_risk

        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif not predicted and not expected:
            tn += 1
        else:
            fn += 1

        signals_ok = True
        if case.expected_signals:
            actual_signals = {
                "missed_deadlines": result.signals.missed_deadlines,
                "inactive": result.signals.inactive,
                "low_progress": result.signals.low_progress,
                "low_feedback": result.signals.low_feedback,
            }
            signals_ok = actual_signals == case.expected_signals
            if not signals_ok:
                signal_mismatches.append(
                    {"case": case.name, "expected": case.expected_signals, "actual": actual_signals}
                )

        case_results.append(
            {
                "case": case.name,
                "learner_id": case.progress.learner_id,
                "expected_at_risk": expected,
                "predicted_at_risk": predicted,
                "correct": predicted == expected,
                "signals_correct": signals_ok,
            }
        )

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    accuracy = (tp + tn) / len(cases) if cases else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_cases": len(cases),
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "signal_mismatches": signal_mismatches,
        "case_results": case_results,
    }


def generate_report(report: dict) -> str:
    """Write the report to evals/reports/, matching the existing eval suite's convention."""
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"atrisk_eval_report_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    return report_path


def main(min_precision: float = 1.0, write_report: bool = True) -> int:
    """Run the at-risk detector eval suite and print/report the results.

    Args:
        min_precision: Minimum acceptable precision — the process exits
            non-zero below this bar, so it can gate CI.
        write_report: Whether to write a JSON report to evals/reports/.

    Returns:
        Process exit code (0 = passed the precision bar, 1 = failed).
    """
    report = run_suite()

    print("=" * 60)
    print("At-Risk Detector Evaluation".center(60))
    print("=" * 60)
    print(f"Cases:      {report['total_cases']}")
    print(f"Precision:  {report['precision']}")
    print(f"Recall:     {report['recall']}")
    print(f"F1:         {report['f1']}")
    print(f"Accuracy:   {report['accuracy']}")

    if report["signal_mismatches"]:
        print(f"\n{len(report['signal_mismatches'])} case(s) had incorrect individual signals:")
        for mismatch in report["signal_mismatches"]:
            print(f"  - {mismatch['case']}: expected {mismatch['expected']}, got {mismatch['actual']}")

    if write_report:
        path = generate_report(report)
        print(f"\nReport written to: {path}")

    logger.info(
        "atrisk_eval_completed",
        precision=report["precision"],
        recall=report["recall"],
        f1=report["f1"],
        accuracy=report["accuracy"],
    )

    passed = report["precision"] >= min_precision
    if not passed:
        print(f"\nFAILED — precision {report['precision']} is below the required {min_precision} bar.")
        return 1

    print("\nPASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
