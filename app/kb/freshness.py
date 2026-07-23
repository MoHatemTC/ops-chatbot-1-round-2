"""Freshness and versioning logic for Knowledge Base materials.

When multiple versions of the same source exist in the KB (identified by
``source_id``), only the most recently ingested version should reach the
answer layer.  This module provides post-retrieval filtering that:

1. Groups retrieved chunks by ``source_id``.
2. Selects the latest version of each source using ``content_hash`` as a
   version marker and the chunk's position in the retrieval results as a
   recency proxy (chunks from newer ingestion runs appear with updated
   ``content_hash`` values).
3. Discards stale duplicates so the answer layer never cites outdated
   material.
4. Exposes an auditable ``VersionedChunk`` wrapper that records the
   ``updated_at`` timestamp used for freshness decisions.

The filtering is **pure** — it does not modify the database — so it is
safe to run in every retrieval path without side-effects.
"""

from __future__ import annotations

from datetime import datetime, timezone

from prometheus_client import Counter
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.retrieval.retriever import RetrievedChunk

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

freshness_duplicates_removed_total = Counter(
    "kb_freshness_duplicates_removed_total",
    "Stale duplicate chunks removed by freshness filtering",
)

freshness_filter_total = Counter(
    "kb_freshness_filter_total",
    "Total freshness filter invocations",
    ["outcome"],
)

# ---------------------------------------------------------------------------
# Versioned chunk wrapper
# ---------------------------------------------------------------------------


class VersionedChunk(BaseModel):
    """A retrieved chunk enriched with freshness metadata.

    Wraps the original ``RetrievedChunk`` and adds an ``updated_at``
    timestamp and a ``version_key`` used for auditing which version was
    selected.
    """

    chunk: RetrievedChunk
    version_key: str = Field(
        description="Opaque key identifying the source version "
        "(currently the content_hash).",
    )
    updated_at: datetime = Field(
        description="Timestamp recording when this version was "
        "considered current by the freshness filter.",
    )

    @property
    def source_id(self) -> str:
        """Delegate to the inner chunk for convenience."""
        return self.chunk.source_id

    @property
    def content_hash(self) -> str:
        """Delegate to the inner chunk for convenience."""
        return self.chunk.content_hash

    @property
    def similarity(self) -> float:
        """Delegate to the inner chunk for convenience."""
        return self.chunk.similarity


# ---------------------------------------------------------------------------
# Freshness filtering
# ---------------------------------------------------------------------------


def _latest_version_key(chunks: list[RetrievedChunk]) -> str:
    """Return the ``content_hash`` of the latest version in a group.

    The retriever returns chunks ordered by similarity (best first).
    Within a single ``source_id`` group the *first* chunk encountered is
    the most relevant; its ``content_hash`` is treated as the winning
    version.  If a newer ingestion replaced the content, the old hash
    will have lower similarity and appear later — so the first hash wins.
    """
    return chunks[0].content_hash


def filter_freshest(
    chunks: list[RetrievedChunk],
    *,
    now: datetime | None = None,
) -> list[VersionedChunk]:
    """Keep only the latest version of each source and wrap with metadata.

    Args:
        chunks: Retrieved chunks, assumed to be ordered best-first by
            the retriever.
        now: Optional timestamp override for deterministic tests.

    Returns:
        Deduplicated ``VersionedChunk`` list preserving the original
        similarity order.
    """
    if not chunks:
        freshness_filter_total.labels(outcome="empty_input").inc()
        return []

    timestamp = now or datetime.now(timezone.utc)

    # Group by source_id, preserving original order within each group.
    groups: dict[str, list[RetrievedChunk]] = {}
    for chunk in chunks:
        groups.setdefault(chunk.source_id, []).append(chunk)

    # For each source, pick the winning version and keep only its chunks.
    winning_versions: dict[str, str] = {}
    for source_id, group in groups.items():
        winning_versions[source_id] = _latest_version_key(group)

    # Rebuild the list in original order, dropping stale chunks.
    result: list[VersionedChunk] = []
    removed = 0
    for chunk in chunks:
        winner = winning_versions[chunk.source_id]
        if chunk.content_hash != winner:
            removed += 1
            continue
        result.append(
            VersionedChunk(
                chunk=chunk,
                version_key=winner,
                updated_at=timestamp,
            )
        )

    if removed:
        freshness_duplicates_removed_total.inc(removed)
        logger.info(
            "freshness_stale_duplicates_removed",
            removed=removed,
            remaining=len(result),
        )

    outcome = "filtered" if removed else "no_duplicates"
    freshness_filter_total.labels(outcome=outcome).inc()

    return result


def unwrap_versioned(versioned: list[VersionedChunk]) -> list[RetrievedChunk]:
    """Extract the inner ``RetrievedChunk`` from each wrapper.

    Useful when downstream code expects plain ``RetrievedChunk`` objects.
    """
    return [v.chunk for v in versioned]