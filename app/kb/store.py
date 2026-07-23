"""Knowledge base store: chunk, embed, and persist approved materials.

This module owns the *write* side of the knowledge base for Grounded Q&A (M1).
It is built around two small interfaces so the ingestion logic can be unit
tested without a live database or a real embedding API:

* :class:`Embedder` turns chunk text into vectors.
* :class:`ChunkRepository` persists chunks and answers the "has this source
  changed?" question that powers update-not-duplicate ingestion.

The default production wiring uses OpenAI embeddings and a ``pgvector``-backed
Postgres table, but :class:`KBStore` depends only on the protocols, so tests
inject in-memory fakes. See ``tests/test_ingestion.py``.
"""

from typing import (
    Protocol,
    runtime_checkable,
)

from sqlalchemy import (
    Engine,
    text,
)
from sqlmodel import Session

from app.core.config import settings
from app.core.logging import logger
from app.schemas.knowledge import (
    IngestionStats,
    KnowledgeChunk,
    RawMaterial,
    normalize_content,
)

# Dimensionality of ``text-embedding-3-small`` (the project's default embedder).
DEFAULT_EMBEDDING_DIM = 1536

# Physical table backing the knowledge base. Owned entirely by this lane; it is
# created idempotently by :class:`PgVectorChunkRepository` so no shared Alembic
# migration needs to change.
_TABLE_NAME = "knowledge_chunks"


@runtime_checkable
class Embedder(Protocol):
    """Turns text into embedding vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: The chunk texts to embed.

        Returns:
            One embedding vector per input text, in the same order.
        """
        ...


class ChunkRepository(Protocol):
    """Persistence boundary for knowledge base chunks.

    Implementations must make :meth:`replace_source` atomic: either the old
    chunks for a source are fully replaced by the new ones, or nothing changes.
    """

    def get_source_hash(self, source_id: str) -> str | None:
        """Return the stored content hash for a source, or ``None`` if unknown.

        Args:
            source_id: Stable identity of the material.

        Returns:
            The content hash last stored for the source, or ``None`` when the
            source has never been ingested.
        """
        ...

    def replace_source(
        self,
        source_id: str,
        chunks: list[KnowledgeChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Atomically replace all stored chunks for a source.

        Args:
            source_id: Stable identity of the material being written.
            chunks: The new chunks for the source (may be empty).
            embeddings: One vector per chunk, aligned by index.
        """
        ...


def chunk_document(
    material: RawMaterial,
    *,
    max_chars: int = 1000,
    overlap: int = 150,
) -> list[KnowledgeChunk]:
    """Split a material into deterministic, metadata-carrying chunks.

    Paragraphs are packed greedily up to ``max_chars``; any single paragraph
    longer than ``max_chars`` is windowed with ``overlap`` characters of
    context carried between windows. The algorithm is pure and deterministic so
    re-ingesting identical content yields identical chunks.

    Args:
        material: The document to split.
        max_chars: Soft upper bound on chunk size in characters.
        overlap: Characters of overlap when splitting oversized paragraphs.

    Returns:
        The ordered chunks. Empty content yields an empty list.

    Raises:
        ValueError: If ``overlap`` is not smaller than ``max_chars``.
    """
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")

    body = normalize_content(material.content)
    if not body:
        return []

    paragraphs = [para.strip() for para in body.split("\n\n") if para.strip()]

    packed: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + 2 + len(para) <= max_chars:
            current = f"{current}\n\n{para}"
        else:
            packed.append(current)
            current = para
    if current:
        packed.append(current)

    windows: list[str] = []
    for block in packed:
        if len(block) <= max_chars:
            windows.append(block)
            continue
        start = 0
        step = max_chars - overlap
        while start < len(block):
            windows.append(block[start : start + max_chars])
            start += step

    return [
        KnowledgeChunk(
            metadata=material.metadata,
            source_id=material.source_id,
            content_hash=material.content_hash,
            chunk_index=index,
            content=window,
        )
        for index, window in enumerate(windows)
    ]


class KBStore:
    """Ingest approved materials into the knowledge base, idempotently.

    The store never blindly re-writes: a material whose content hash matches the
    stored hash is skipped, so re-running ingestion on an unchanged corpus does
    no writes and issues no embedding calls. Changed or new materials have their
    chunks replaced atomically, which is what makes refreshes update-not-
    duplicate.
    """

    def __init__(self, repository: ChunkRepository, embedder: Embedder) -> None:
        """Initialize the store.

        Args:
            repository: Persistence backend for chunks.
            embedder: Embedding provider for chunk text.
        """
        self._repository = repository
        self._embedder = embedder

    def ingest(self, materials: list[RawMaterial]) -> IngestionStats:
        """Ingest a batch of materials, skipping unchanged ones.

        Args:
            materials: The approved documents to ingest.

        Returns:
            Counts describing what happened during the run.
        """
        stats = IngestionStats()
        for material in materials:
            stats.sources_seen += 1
            stored_hash = self._repository.get_source_hash(material.source_id)

            if stored_hash == material.content_hash:
                stats.sources_skipped += 1
                logger.info(
                    "kb_ingest_skipped_unchanged",
                    source_id=material.source_id,
                    cohort=material.metadata.cohort,
                )
                continue

            chunks = chunk_document(material)
            embeddings = self._embedder.embed([chunk.content for chunk in chunks]) if chunks else []
            self._repository.replace_source(material.source_id, chunks, embeddings)

            stats.sources_ingested += 1
            stats.chunks_written += len(chunks)
            logger.info(
                "kb_ingest_source_written",
                source_id=material.source_id,
                cohort=material.metadata.cohort,
                type=material.metadata.type.value,
                chunks=len(chunks),
            )

        logger.info(
            "kb_ingest_completed",
            sources_seen=stats.sources_seen,
            sources_ingested=stats.sources_ingested,
            sources_skipped=stats.sources_skipped,
            chunks_written=stats.chunks_written,
        )
        return stats
    def list_materials(self) -> list[dict]:
        """List all materials currently in the knowledge base, with freshness info."""
        return self._repository.list_sources()

    def retire_material(self, source_id: str) -> bool:
        """Retire a material from the knowledge base.

        Args:
            source_id: Stable identity of the material to retire.

        Returns:
            True if the material was found and retired, False if it didn't exist.
        """
        retired = self._repository.retire_source(source_id)
        logger.info("kb_material_retired", source_id=source_id, retired=retired)
        return retired


class OpenAIEmbedder:
    """Default :class:`Embedder` backed by OpenAI embeddings via LangChain.

    The heavy ``langchain_openai`` import is deferred to construction so this
    module (and the tests that import it) stay import-light and do not require
    network access or an API key just to be loaded.
    """

    def __init__(self, model: str | None = None) -> None:
        """Initialize the embedder.

        Args:
            model: Embedding model name; defaults to the project setting
                ``LONG_TERM_MEMORY_EMBEDDER_MODEL``.
        """
        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        self._model = model or settings.LONG_TERM_MEMORY_EMBEDDER_MODEL
        self._client = OpenAIEmbeddings(model=self._model, api_key=SecretStr(settings.OPENAI_API_KEY))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts with the configured OpenAI model.

        Args:
            texts: The chunk texts to embed.

        Returns:
            One embedding vector per input text, in order.
        """
        if not texts:
            return []
        return self._client.embed_documents(texts)


def _to_vector_literal(embedding: list[float]) -> str:
    """Render an embedding as a ``pgvector`` text literal (``[1,2,3]``)."""
    return "[" + ",".join(repr(value) for value in embedding) + "]"


class PgVectorChunkRepository:
    """A :class:`ChunkRepository` backed by a ``pgvector`` Postgres table.

    The table and the ``vector`` extension are created on demand with idempotent
    DDL, keeping this feature self-contained within its assigned files. Writes
    for a source happen inside a single transaction so a refresh can never leave
    a half-replaced source behind.
    """

    def __init__(self, engine: Engine, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        """Initialize the repository and ensure its table exists.

        Args:
            engine: SQLAlchemy engine pointing at the application database.
            embedding_dim: Dimensionality of stored vectors.
        """
        self._engine = engine
        self._embedding_dim = embedding_dim
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the pgvector extension, table, and index if missing."""
        ddl = [
            "CREATE EXTENSION IF NOT EXISTS vector;",
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                id BIGSERIAL PRIMARY KEY,
                source_id TEXT NOT NULL,
                cohort TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                type TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector({self._embedding_dim}),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            f"CREATE INDEX IF NOT EXISTS ix_{_TABLE_NAME}_source_id ON {_TABLE_NAME} (source_id);",
            f"CREATE INDEX IF NOT EXISTS ix_{_TABLE_NAME}_cohort ON {_TABLE_NAME} (cohort);",
        ]
        with Session(self._engine) as session:
            for statement in ddl:
                session.execute(text(statement))
            session.commit()

    def get_source_hash(self, source_id: str) -> str | None:
        """Return the stored content hash for a source, or ``None``."""
        with Session(self._engine) as session:
            row = session.execute(
                text(f"SELECT content_hash FROM {_TABLE_NAME} WHERE source_id = :sid LIMIT 1"),
                {"sid": source_id},
            ).first()
        return row[0] if row is not None else None

    def replace_source(
        self,
        source_id: str,
        chunks: list[KnowledgeChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Delete existing chunks for a source and insert the new ones atomically."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")

        insert_sql = text(
            f"""
            INSERT INTO {_TABLE_NAME}
                (source_id, cohort, title, source, type, content_hash, chunk_index, content, embedding)
            VALUES
                (:source_id, :cohort, :title, :source, :type, :content_hash, :chunk_index, :content,
                 CAST(:embedding AS vector))
            """
        )
        with Session(self._engine) as session:
            session.execute(
                text(f"DELETE FROM {_TABLE_NAME} WHERE source_id = :sid"),
                {"sid": source_id},
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                session.execute(
                    insert_sql,
                    {
                        "source_id": chunk.source_id,
                        "cohort": chunk.metadata.cohort,
                        "title": chunk.metadata.title,
                        "source": chunk.metadata.source,
                        "type": chunk.metadata.type.value,
                        "content_hash": chunk.content_hash,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "embedding": _to_vector_literal(embedding),
                    },
                )
            session.commit()


def build_default_store() -> KBStore:
    """Wire a production :class:`KBStore` from application settings.

    Uses the shared database engine and OpenAI embeddings. Imports of shared
    singletons are deferred so importing this module never triggers database or
    embedding-client initialization.

    Returns:
        A ready-to-use store backed by pgvector and OpenAI embeddings.
    """
    from app.services.database import database_service

    repository = PgVectorChunkRepository(database_service.engine)
    embedder = OpenAIEmbedder()
    return KBStore(repository=repository, embedder=embedder)