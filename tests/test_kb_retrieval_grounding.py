"""Tests for cohort scoping, freshness filtering, confidence gating, and answer integration.

Uses deterministic in-memory fakes — no live database, LLM, or embedding
service needed.  All tests are synchronous-safe via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any

import pytest

from app.kb.cohort import (
    CohortScopedRetriever,
    CohortValidationError,
    validate_cohort,
)
from app.kb.freshness import (
    VersionedChunk,
    filter_freshest,
    unwrap_versioned,
)
from app.retrieval.confidence import (
    ConfidenceDecision,
    compute_confidence,
    gate_chunks,
)
from app.retrieval.retriever import RetrievedChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from a sync test."""
    return asyncio.run(coro)


def _chunk(
    *,
    source_id: str = "cohort-a::schedules/july.md",
    title: str = "July Cohort Schedule",
    source: str = "schedules/july.md",
    source_type: str = "schedule",
    cohort: str = "cohort-a",
    content_hash: str = "hash-v1",
    chunk_index: int = 0,
    content: str = "The final project deadline is July 30 at 11:59 PM.",
    distance: float = 0.08,
    similarity: float = 0.92,
) -> RetrievedChunk:
    """Build a test chunk with sensible defaults."""
    return RetrievedChunk(
        source_id=source_id,
        title=title,
        source=source,
        source_type=source_type,
        cohort=cohort,
        content_hash=content_hash,
        chunk_index=chunk_index,
        content=content,
        distance=distance,
        similarity=similarity,
    )


class FakeRetriever:
    """In-memory retriever that returns pre-loaded chunks."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        """Store pre-loaded chunks for testing."""
        self._chunks = chunks

    async def retrieve(
        self,
        query: str,
        *,
        cohort: str,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Return chunks filtered by cohort, limited by top_k."""
        filtered = [c for c in self._chunks if c.cohort == cohort]
        return filtered[:top_k]


class FailingRetriever:
    """Retriever that always raises an exception."""

    async def retrieve(
        self,
        query: str,
        *,
        cohort: str,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Simulate a retrieval failure."""
        raise RuntimeError("database connection lost")


# ===================================================================
# Cohort validation tests
# ===================================================================


class TestCohortValidation:
    """Tests for the ``validate_cohort`` helper."""

    def test_valid_cohort_returned_stripped(self) -> None:
        """A padded but valid cohort string is stripped and returned."""
        assert validate_cohort("  cohort-a  ") == "cohort-a"

    def test_none_raises(self) -> None:
        """None cohort is rejected."""
        with pytest.raises(CohortValidationError):
            validate_cohort(None)

    def test_empty_string_raises(self) -> None:
        """An empty string is rejected."""
        with pytest.raises(CohortValidationError):
            validate_cohort("")

    def test_single_char_raises(self) -> None:
        """A single character is too short."""
        with pytest.raises(CohortValidationError):
            validate_cohort("a")

    def test_too_long_raises(self) -> None:
        """An excessively long string is rejected."""
        with pytest.raises(CohortValidationError):
            validate_cohort("x" * 200)


# ===================================================================
# Cohort-scoped retriever tests
# ===================================================================


class TestCohortScopedRetriever:
    """Tests for ``CohortScopedRetriever``."""

    def test_returns_only_matching_cohort(self) -> None:
        """Chunks from a different cohort are never returned."""
        chunks = [
            _chunk(cohort="cohort-a", source_id="a::doc1"),
            _chunk(cohort="cohort-b", source_id="b::doc2"),
        ]
        retriever = CohortScopedRetriever(FakeRetriever(chunks))
        result = _run(retriever.retrieve("deadline?", cohort="cohort-a"))

        assert all(c.cohort == "cohort-a" for c in result)
        assert len(result) == 1

    def test_empty_query_returns_nothing(self) -> None:
        """Blank queries produce no results."""
        retriever = CohortScopedRetriever(FakeRetriever([_chunk()]))
        result = _run(retriever.retrieve("   ", cohort="cohort-a"))

        assert result == []

    def test_invalid_cohort_raises(self) -> None:
        """A missing cohort raises CohortValidationError."""
        retriever = CohortScopedRetriever(FakeRetriever([]))
        with pytest.raises(CohortValidationError):
            _run(retriever.retrieve("question", cohort=""))

    def test_none_cohort_raises(self) -> None:
        """A None cohort raises CohortValidationError."""
        retriever = CohortScopedRetriever(FakeRetriever([]))
        with pytest.raises(CohortValidationError):
            _run(retriever.retrieve("question", cohort=None))

    def test_retriever_failure_returns_empty(self) -> None:
        """If the inner retriever throws, the wrapper returns an empty list."""
        retriever = CohortScopedRetriever(FailingRetriever())
        result = _run(retriever.retrieve("question", cohort="cohort-a"))

        assert result == []

    def test_leakage_blocked(self) -> None:
        """Defence-in-depth: chunks leaking from the repository are dropped."""
        # Simulate a buggy repository that ignores the cohort filter.
        leaked_chunk = _chunk(cohort="cohort-b", source_id="b::leaked")

        class LeakyRetriever:
            async def retrieve(self, query: str, *, cohort: str, top_k: int = 5) -> list[RetrievedChunk]:
                return [leaked_chunk]

        retriever = CohortScopedRetriever(LeakyRetriever())
        result = _run(retriever.retrieve("question", cohort="cohort-a"))

        assert result == []


# ===================================================================
# Freshness filtering tests
# ===================================================================


class TestFreshnessFilter:
    """Tests for ``filter_freshest`` and ``unwrap_versioned``."""

    def test_empty_input(self) -> None:
        """No chunks in means no chunks out."""
        assert filter_freshest([]) == []

    def test_single_version_kept(self) -> None:
        """A single chunk passes through with a version wrapper."""
        chunk = _chunk()
        result = filter_freshest([chunk])

        assert len(result) == 1
        assert isinstance(result[0], VersionedChunk)
        assert result[0].chunk is chunk
        assert result[0].version_key == chunk.content_hash

    def test_stale_duplicate_removed(self) -> None:
        """When two versions of the same source exist, only the latest is kept."""
        new = _chunk(
            source_id="cohort-a::policy.md",
            content_hash="hash-v2",
            content="Updated policy content.",
            similarity=0.90,
        )
        old = _chunk(
            source_id="cohort-a::policy.md",
            content_hash="hash-v1",
            content="Old policy content.",
            similarity=0.85,
        )
        # new appears first (higher similarity = more relevant = winning version)
        result = filter_freshest([new, old])

        assert len(result) == 1
        assert result[0].content_hash == "hash-v2"

    def test_different_sources_both_kept(self) -> None:
        """Chunks from different sources are not affected by dedup."""
        a = _chunk(source_id="a::faq.md", content_hash="h1")
        b = _chunk(source_id="b::schedule.md", content_hash="h2")
        result = filter_freshest([a, b])

        assert len(result) == 2

    def test_unwrap_returns_plain_chunks(self) -> None:
        """unwrap_versioned extracts the inner RetrievedChunk."""
        chunk = _chunk()
        versioned = filter_freshest([chunk])
        unwrapped = unwrap_versioned(versioned)

        assert len(unwrapped) == 1
        assert unwrapped[0] is chunk

    def test_custom_timestamp(self) -> None:
        """A deterministic timestamp can be injected for tests."""
        fixed_time = datetime(2026, 7, 23, tzinfo=timezone.utc)
        result = filter_freshest([_chunk()], now=fixed_time)

        assert result[0].updated_at == fixed_time


# ===================================================================
# Confidence gating tests
# ===================================================================


class TestConfidenceGating:
    """Tests for ``compute_confidence`` and ``gate_chunks``."""

    def test_no_chunks_returns_no_evidence(self) -> None:
        """Empty input gets the no_evidence decision."""
        result = compute_confidence([])

        assert result.decision == ConfidenceDecision.NO_EVIDENCE
        assert result.needs_escalation is True
        assert result.score == 0.0

    def test_high_similarity_passes(self) -> None:
        """Chunks with high similarity pass the threshold."""
        chunks = [
            _chunk(similarity=0.90),
            _chunk(similarity=0.85, chunk_index=1),
        ]
        result = compute_confidence(chunks, threshold=0.55)

        assert result.decision == ConfidenceDecision.SUFFICIENT
        assert result.needs_escalation is False
        assert result.score > 0.55

    def test_low_similarity_fails(self) -> None:
        """Chunks below threshold produce an insufficient decision."""
        chunks = [
            _chunk(similarity=0.30),
            _chunk(similarity=0.25, chunk_index=1),
        ]
        result = compute_confidence(chunks, threshold=0.55)

        assert result.decision == ConfidenceDecision.INSUFFICIENT
        assert result.needs_escalation is True

    def test_gate_chunks_returns_empty_on_failure(self) -> None:
        """gate_chunks returns no accepted chunks when confidence is low."""
        chunks = [_chunk(similarity=0.20)]
        result, accepted = gate_chunks(chunks, threshold=0.55)

        assert result.needs_escalation is True
        assert accepted == []

    def test_gate_chunks_returns_chunks_on_success(self) -> None:
        """gate_chunks returns the full chunk list when confidence passes."""
        chunks = [_chunk(similarity=0.90)]
        result, accepted = gate_chunks(chunks, threshold=0.55)

        assert result.needs_escalation is False
        assert len(accepted) == 1

    def test_threshold_boundary_below(self) -> None:
        """A score exactly below the threshold is insufficient."""
        chunk = _chunk(similarity=0.549)
        result = compute_confidence([chunk], threshold=0.55)

        assert result.decision == ConfidenceDecision.INSUFFICIENT

    def test_threshold_boundary_at(self) -> None:
        """A score exactly at the threshold is sufficient."""
        chunk = _chunk(similarity=0.55)
        result = compute_confidence([chunk], threshold=0.55)

        assert result.decision == ConfidenceDecision.SUFFICIENT

    def test_min_chunks_enforced(self) -> None:
        """Fewer chunks than min_chunks triggers insufficient."""
        chunk = _chunk(similarity=0.95)
        result = compute_confidence([chunk], threshold=0.55, min_chunks=2)

        assert result.decision == ConfidenceDecision.INSUFFICIENT
        assert result.needs_escalation is True


# ===================================================================
# Integration: full pipeline with fakes
# ===================================================================


class TestFullPipelineIntegration:
    """End-to-end tests combining cohort → freshness → confidence."""

    def test_happy_path(self) -> None:
        """High-quality chunks from the right cohort pass all gates."""
        chunks = [
            _chunk(cohort="cohort-a", similarity=0.92, content_hash="v2"),
            _chunk(
                cohort="cohort-a",
                similarity=0.88,
                content_hash="v2",
                chunk_index=1,
                content="Additional schedule details.",
            ),
        ]

        # Step 1: Cohort retrieval
        retriever = CohortScopedRetriever(FakeRetriever(chunks))
        scoped = _run(retriever.retrieve("deadline?", cohort="cohort-a"))
        assert len(scoped) == 2

        # Step 2: Freshness
        versioned = filter_freshest(scoped)
        fresh = unwrap_versioned(versioned)
        assert len(fresh) == 2

        # Step 3: Confidence
        result, accepted = gate_chunks(fresh, threshold=0.55)
        assert result.decision == ConfidenceDecision.SUFFICIENT
        assert len(accepted) == 2

    def test_stale_removed_then_confident(self) -> None:
        """Stale duplicates are removed before confidence is checked."""
        chunks = [
            _chunk(
                source_id="a::policy.md",
                content_hash="v2",
                similarity=0.90,
            ),
            _chunk(
                source_id="a::policy.md",
                content_hash="v1",
                similarity=0.80,
            ),
        ]

        retriever = CohortScopedRetriever(FakeRetriever(chunks))
        scoped = _run(retriever.retrieve("attendance policy?", cohort="cohort-a"))

        versioned = filter_freshest(scoped)
        fresh = unwrap_versioned(versioned)
        assert len(fresh) == 1
        assert fresh[0].content_hash == "v2"

        result, accepted = gate_chunks(fresh, threshold=0.55)
        assert result.decision == ConfidenceDecision.SUFFICIENT

    def test_wrong_cohort_blocked(self) -> None:
        """Chunks from a foreign cohort never reach the confidence gate."""
        chunks = [_chunk(cohort="cohort-b", similarity=0.95)]

        retriever = CohortScopedRetriever(FakeRetriever(chunks))
        scoped = _run(retriever.retrieve("question", cohort="cohort-a"))
        assert scoped == []

        result = compute_confidence(scoped)
        assert result.decision == ConfidenceDecision.NO_EVIDENCE
        assert result.needs_escalation is True

    def test_low_confidence_triggers_escalation(self) -> None:
        """Weak evidence is caught by the confidence gate."""
        chunks = [_chunk(cohort="cohort-a", similarity=0.30)]

        retriever = CohortScopedRetriever(FakeRetriever(chunks))
        scoped = _run(retriever.retrieve("obscure question", cohort="cohort-a"))

        versioned = filter_freshest(scoped)
        fresh = unwrap_versioned(versioned)

        result, accepted = gate_chunks(fresh, threshold=0.55)
        assert result.needs_escalation is True
        assert accepted == []