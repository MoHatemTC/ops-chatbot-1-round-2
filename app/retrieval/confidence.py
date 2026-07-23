"""Confidence thresholding for retrieval-grounded answers.

After cohort-scoped retrieval and freshness filtering, the answer layer
needs to decide whether the retrieved evidence is strong enough to
generate a grounded response.  This module encapsulates that decision:

* **Above threshold** → the evidence is considered sufficient and the
  answer layer may proceed.
* **Below threshold** → the query is gated; the answer layer must
  produce an honest refusal and emit an escalation signal so a human
  operator can follow up.

The threshold is configurable and should be calibrated against the
production corpus and evaluation set.  The default (0.55) is
deliberately conservative — it is better to refuse honestly than to
hallucinate.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.retrieval.retriever import RetrievedChunk

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIDENCE_THRESHOLD = 0.55
"""Minimum mean similarity for evidence to be considered sufficient."""

DEFAULT_MIN_CHUNKS = 1
"""Minimum number of chunks required for a confident answer."""

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

confidence_decisions_total = Counter(
    "kb_confidence_decisions_total",
    "Total confidence gate decisions",
    ["decision"],
)

confidence_score_histogram = Histogram(
    "kb_confidence_score",
    "Distribution of computed confidence scores",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ConfidenceDecision(str, Enum):
    """Outcome of the confidence gate."""

    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    NO_EVIDENCE = "no_evidence"


class ConfidenceResult(BaseModel):
    """Structured result of the confidence check.

    Attributes:
        decision: Whether the evidence passes the threshold.
        score: Computed confidence score (mean similarity of top chunks).
        threshold: The threshold that was applied.
        chunk_count: Number of chunks evaluated.
        needs_escalation: True when the answer layer must refuse and
            escalate to a human.
        escalation_reason: Human-readable reason for escalation, or
            ``None`` when confidence is sufficient.
    """

    decision: ConfidenceDecision
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    chunk_count: int = Field(ge=0)
    needs_escalation: bool
    escalation_reason: str | None = None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def compute_confidence(
    chunks: Sequence[RetrievedChunk],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    min_chunks: int = DEFAULT_MIN_CHUNKS,
) -> ConfidenceResult:
    """Evaluate whether retrieved evidence meets the confidence threshold.

    The confidence score is the **mean similarity** of the provided
    chunks.  This is a simple, explainable metric that correlates well
    with answer quality in early evaluations.  It can be replaced with a
    learned calibrator once evaluation data is available.

    Args:
        chunks: Retrieved chunks after cohort and freshness filtering.
        threshold: Minimum mean similarity required.
        min_chunks: Minimum number of chunks needed.

    Returns:
        A ``ConfidenceResult`` with the gate decision and metrics.
    """
    if not chunks:
        confidence_decisions_total.labels(decision="no_evidence").inc()
        confidence_score_histogram.observe(0.0)
        return ConfidenceResult(
            decision=ConfidenceDecision.NO_EVIDENCE,
            score=0.0,
            threshold=threshold,
            chunk_count=0,
            needs_escalation=True,
            escalation_reason="no_relevant_sources",
        )

    if len(chunks) < min_chunks:
        mean_sim = sum(c.similarity for c in chunks) / len(chunks)
        confidence_score_histogram.observe(mean_sim)
        confidence_decisions_total.labels(decision="insufficient").inc()
        return ConfidenceResult(
            decision=ConfidenceDecision.INSUFFICIENT,
            score=mean_sim,
            threshold=threshold,
            chunk_count=len(chunks),
            needs_escalation=True,
            escalation_reason="insufficient_evidence_chunks",
        )

    mean_similarity = sum(c.similarity for c in chunks) / len(chunks)
    confidence_score_histogram.observe(mean_similarity)

    if mean_similarity < threshold:
        confidence_decisions_total.labels(decision="insufficient").inc()
        logger.info(
            "confidence_below_threshold",
            score=round(mean_similarity, 4),
            threshold=threshold,
            chunk_count=len(chunks),
        )
        return ConfidenceResult(
            decision=ConfidenceDecision.INSUFFICIENT,
            score=mean_similarity,
            threshold=threshold,
            chunk_count=len(chunks),
            needs_escalation=True,
            escalation_reason="low_confidence",
        )

    confidence_decisions_total.labels(decision="sufficient").inc()
    logger.info(
        "confidence_above_threshold",
        score=round(mean_similarity, 4),
        threshold=threshold,
        chunk_count=len(chunks),
    )
    return ConfidenceResult(
        decision=ConfidenceDecision.SUFFICIENT,
        score=mean_similarity,
        threshold=threshold,
        chunk_count=len(chunks),
        needs_escalation=False,
    )


def gate_chunks(
    chunks: Sequence[RetrievedChunk],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    min_chunks: int = DEFAULT_MIN_CHUNKS,
) -> tuple[ConfidenceResult, list[RetrievedChunk]]:
    """Convenience wrapper: check confidence and return accepted chunks.

    Returns:
        A tuple of ``(result, accepted_chunks)``.  When confidence is
        insufficient, ``accepted_chunks`` is an empty list so the caller
        can proceed directly to an honest refusal without extra branching.
    """
    result = compute_confidence(
        chunks, threshold=threshold, min_chunks=min_chunks
    )
    if result.needs_escalation:
        return result, []
    return result, list(chunks)