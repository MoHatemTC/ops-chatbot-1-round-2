"""Cohort-scoped retrieval boundary for the Knowledge Base.

This module enforces strict cohort isolation at the retrieval boundary.
Every query **must** include a validated cohort identifier; requests
without one are rejected before they reach the vector store.  A
defence-in-depth post-filter guarantees that no chunk from another cohort
ever leaks into the answer layer, even if the underlying repository has a
bug.

The module exposes a thin ``CohortScopedRetriever`` wrapper around the
core ``KnowledgeRetriever``.  Graph nodes and service code import *this*
class instead of reaching for the retriever directly, keeping the
isolation rule in one auditable place.
"""

from __future__ import annotations

from typing import Protocol

from prometheus_client import Counter

from app.core.logging import logger
from app.retrieval.retriever import (
    TOP_K,
    RetrievedChunk,
    build_default_retriever,
)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

cohort_retrieval_total = Counter(
    "kb_cohort_retrieval_total",
    "Total cohort-scoped retrieval attempts",
    ["cohort", "outcome"],
)

cohort_leakage_blocked_total = Counter(
    "kb_cohort_leakage_blocked_total",
    "Chunks removed by the post-retrieval cohort guard",
    ["expected_cohort"],
)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_MIN_COHORT_LENGTH = 2
_MAX_COHORT_LENGTH = 128


class CohortValidationError(ValueError):
    """Raised when a cohort identifier is missing or malformed."""


def validate_cohort(cohort: str | None) -> str:
    """Return a normalised cohort string or raise ``CohortValidationError``.

    Accepted values are stripped, non-empty strings between
    ``_MIN_COHORT_LENGTH`` and ``_MAX_COHORT_LENGTH`` characters.
    """
    if cohort is None:
        raise CohortValidationError("cohort must not be None")

    normalised = cohort.strip()
    if len(normalised) < _MIN_COHORT_LENGTH:
        raise CohortValidationError(
            f"cohort must be at least {_MIN_COHORT_LENGTH} characters, "
            f"got {len(normalised)!r}"
        )
    if len(normalised) > _MAX_COHORT_LENGTH:
        raise CohortValidationError(
            f"cohort must be at most {_MAX_COHORT_LENGTH} characters, "
            f"got {len(normalised)!r}"
        )
    return normalised


# ---------------------------------------------------------------------------
# Retriever protocol (for dependency injection in tests)
# ---------------------------------------------------------------------------


class RetrieverProtocol(Protocol):
    """Minimal contract a retriever must satisfy."""

    async def retrieve(
        self,
        query: str,
        *,
        cohort: str,
        top_k: int = TOP_K,
    ) -> list[RetrievedChunk]:
        """Return relevant chunks for the given cohort."""
        ...


# ---------------------------------------------------------------------------
# Cohort-scoped retriever
# ---------------------------------------------------------------------------


class CohortScopedRetriever:
    """Enforce cohort isolation as a single auditable boundary.

    Wraps any retriever satisfying ``RetrieverProtocol`` and adds:

    1. **Pre-retrieval validation** — rejects empty / malformed cohorts.
    2. **Post-retrieval guard** — drops any chunk whose ``cohort`` field
       does not match, as defence-in-depth against repository bugs.
    3. **Prometheus counters** — tracks retrieval outcomes and blocked
       leakage so dashboards can alert on anomalies.
    """

    def __init__(self, retriever: RetrieverProtocol) -> None:
        """Store the inner retriever."""
        self._retriever = retriever

    async def retrieve(
        self,
        query: str,
        *,
        cohort: str | None,
        top_k: int = TOP_K,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks with mandatory cohort scoping.

        Args:
            query: Learner question to search for.
            cohort: Mandatory cohort filter.  ``None`` or blank is rejected.
            top_k: Maximum number of accepted chunks to return.

        Returns:
            Cohort-scoped chunks ordered from highest to lowest similarity.

        Raises:
            CohortValidationError: If the cohort is missing or malformed.
        """
        validated_cohort = validate_cohort(cohort)

        normalised_query = " ".join(query.split())
        if not normalised_query:
            logger.info("cohort_retrieval_empty_query", cohort=validated_cohort)
            cohort_retrieval_total.labels(
                cohort=validated_cohort, outcome="empty_query"
            ).inc()
            return []

        try:
            chunks = await self._retriever.retrieve(
                normalised_query,
                cohort=validated_cohort,
                top_k=top_k,
            )
        except Exception as exc:
            logger.exception(
                "cohort_retrieval_failed",
                cohort=validated_cohort,
                error=str(exc),
            )
            cohort_retrieval_total.labels(
                cohort=validated_cohort, outcome="error"
            ).inc()
            return []

        # Defence-in-depth: drop any chunk that does not belong.
        scoped: list[RetrievedChunk] = []
        for chunk in chunks:
            if chunk.cohort.strip() == validated_cohort:
                scoped.append(chunk)
            else:
                cohort_leakage_blocked_total.labels(
                    expected_cohort=validated_cohort,
                ).inc()
                logger.warning(
                    "cohort_leakage_blocked",
                    expected=validated_cohort,
                    actual=chunk.cohort,
                    source_id=chunk.source_id,
                )

        outcome = "success" if scoped else "no_results"
        cohort_retrieval_total.labels(
            cohort=validated_cohort, outcome=outcome
        ).inc()

        logger.info(
            "cohort_retrieval_completed",
            cohort=validated_cohort,
            total_retrieved=len(chunks),
            after_scope_filter=len(scoped),
        )
        return scoped


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_cohort_scoped_retriever() -> CohortScopedRetriever:
    """Build the production cohort-scoped retriever."""
    return CohortScopedRetriever(build_default_retriever())