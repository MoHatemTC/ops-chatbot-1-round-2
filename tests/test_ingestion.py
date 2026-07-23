"""Tests for knowledge base ingestion.

These tests exercise the ingestion *logic* — hashing, chunking, update-not-
duplicate replacement, and metadata preservation — without a live database or a
real embedding API. Persistence and embedding are replaced by in-memory fakes
injected through the same protocols the production wiring uses, so the suite is
fast and deterministic and runs anywhere ``make check`` runs.
"""

from pathlib import Path

from app.ingestion.loader import load_materials
from app.kb.store import (
    KBStore,
    chunk_document,
)
from app.schemas.knowledge import (
    IngestionStats,
    KnowledgeChunk,
    RawMaterial,
    SourceMetadata,
    SourceType,
    compute_content_hash,
)


class FakeEmbedder:
    """Deterministic embedder that records how many texts it embedded."""

    def __init__(self) -> None:
        """Initialize the call counter."""
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a fixed-width deterministic vector per text and count them."""
        self.calls += len(texts)
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class InMemoryChunkRepository:
    """In-memory stand-in for the pgvector repository.

    Stores, per source id, the content hash and the chunk rows that were last
    written. ``replace_source`` mirrors the atomic delete-then-insert contract
    of the real repository.
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        self.by_source: dict[str, tuple[str, list[KnowledgeChunk]]] = {}

    def get_source_hash(self, source_id: str) -> str | None:
        """Return the stored hash for a source, or ``None``."""
        entry = self.by_source.get(source_id)
        return entry[0] if entry is not None else None

    def replace_source(
        self,
        source_id: str,
        chunks: list[KnowledgeChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Replace all stored chunks for a source."""
        assert len(chunks) == len(embeddings)
        content_hash = chunks[0].content_hash if chunks else ""
        self.by_source[source_id] = (content_hash, chunks)

    def all_chunks(self) -> list[KnowledgeChunk]:
        """Return every stored chunk across all sources."""
        result: list[KnowledgeChunk] = []
        for _, chunks in self.by_source.values():
            result.extend(chunks)
        return result


def _material(content: str, *, cohort: str = "2026-summer", source: str = "faqs/general.md") -> RawMaterial:
    """Build a :class:`RawMaterial` for tests."""
    metadata = SourceMetadata(title="General FAQ", source=source, type=SourceType.FAQ, cohort=cohort)
    return RawMaterial(metadata=metadata, content=content)


def _make_store() -> tuple[KBStore, InMemoryChunkRepository, FakeEmbedder]:
    """Build a store wired with in-memory fakes."""
    repository = InMemoryChunkRepository()
    embedder = FakeEmbedder()
    return KBStore(repository=repository, embedder=embedder), repository, embedder


def test_ingest_writes_chunks_with_required_metadata() -> None:
    """Every stored chunk carries title, source, type, and cohort."""
    store, repository, _ = _make_store()

    stats = store.ingest([_material("What are the office hours?\n\nMon-Fri, 9-5.")])

    assert stats.sources_ingested == 1
    assert stats.chunks_written >= 1
    chunks = repository.all_chunks()
    assert chunks
    for chunk in chunks:
        assert chunk.metadata.title == "General FAQ"
        assert chunk.metadata.source == "faqs/general.md"
        assert chunk.metadata.type is SourceType.FAQ
        assert chunk.metadata.cohort == "2026-summer"


def test_reingest_identical_is_idempotent() -> None:
    """Re-ingesting unchanged content writes nothing and skips embedding."""
    store, repository, embedder = _make_store()
    material = _material("Deadlines are posted every Monday.\n\nCheck the portal.")

    first = store.ingest([material])
    chunks_after_first = len(repository.all_chunks())
    embed_calls_after_first = embedder.calls

    second = store.ingest([material])

    assert first.sources_ingested == 1
    assert second.sources_ingested == 0
    assert second.sources_skipped == 1
    # No duplication: chunk count is unchanged on the second run.
    assert len(repository.all_chunks()) == chunks_after_first
    # No wasted embedding work on an unchanged source.
    assert embedder.calls == embed_calls_after_first


def test_reingest_changed_content_replaces_not_duplicates() -> None:
    """Changed content replaces the old chunks rather than adding to them."""
    store, repository, _ = _make_store()
    source = "faqs/general.md"

    store.ingest([_material("Version one of the answer.", source=source)])
    first_chunks = repository.all_chunks()
    assert all("Version one" in chunk.content for chunk in first_chunks)

    stats = store.ingest([_material("Version two is completely different.", source=source)])

    assert stats.sources_ingested == 1
    stored = repository.all_chunks()
    # Old content is gone; only the new version remains for this source.
    assert all("Version two" in chunk.content for chunk in stored)
    assert not any("Version one" in chunk.content for chunk in stored)


def test_cohorts_do_not_leak() -> None:
    """The same source in two cohorts is stored independently."""
    store, repository, _ = _make_store()
    source = "faqs/general.md"

    store.ingest([_material("Cohort A schedule.", cohort="cohort-a", source=source)])
    store.ingest([_material("Cohort B schedule.", cohort="cohort-b", source=source)])

    cohorts = {chunk.metadata.cohort for chunk in repository.all_chunks()}
    assert cohorts == {"cohort-a", "cohort-b"}
    assert len(repository.by_source) == 2


def test_content_hash_is_stable_under_cosmetic_whitespace() -> None:
    """Trailing whitespace and CRLF do not change the idempotency key."""
    assert compute_content_hash("hello\r\nworld  ") == compute_content_hash("hello\nworld")


def test_chunk_indices_are_sequential() -> None:
    """Chunk indices start at zero and increase without gaps."""
    long_body = "\n\n".join(f"Paragraph number {i} with some filler text." for i in range(50))
    chunks = chunk_document(_material(long_body), max_chars=120, overlap=20)

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_empty_material_produces_no_chunks() -> None:
    """Whitespace-only content yields zero chunks and no ingested source."""
    store, repository, embedder = _make_store()

    stats = store.ingest([_material("   \n\n   ")])

    assert stats.chunks_written == 0
    assert repository.all_chunks() == []
    assert embedder.calls == 0


def test_loader_reads_directory_tree(tmp_path: Path) -> None:
    """The loader tags materials by directory and stamps the cohort."""
    (tmp_path / "faqs").mkdir()
    (tmp_path / "onboarding").mkdir()
    (tmp_path / "faqs" / "general.md").write_text("# General\n\nWelcome to the program.", encoding="utf-8")
    (tmp_path / "onboarding" / "day1.md").write_text("# Day One\n\nSet up your laptop.", encoding="utf-8")

    materials = load_materials(tmp_path, cohort="cohort-x")

    assert len(materials) == 2
    types = {material.metadata.type for material in materials}
    assert types == {SourceType.FAQ, SourceType.ONBOARDING}
    assert all(material.metadata.cohort == "cohort-x" for material in materials)


def test_loader_renders_faq_json(tmp_path: Path) -> None:
    """FAQ JSON is rendered into readable question/answer text."""
    (tmp_path / "faqs").mkdir()
    (tmp_path / "faqs" / "faq.json").write_text(
        '[{"question": "When do sessions start?", "answer": "At 10 AM."}]',
        encoding="utf-8",
    )

    materials = load_materials(tmp_path, cohort="cohort-x")

    assert len(materials) == 1
    assert "When do sessions start?" in materials[0].content
    assert "At 10 AM." in materials[0].content


def test_ingestion_stats_default_to_zero() -> None:
    """A fresh stats object starts at zero on every counter."""
    stats = IngestionStats()
    assert (stats.sources_seen, stats.sources_ingested, stats.sources_skipped, stats.chunks_written) == (0, 0, 0, 0)