"""Pydantic schemas for the knowledge base ingestion pipeline.

These schemas are the shared contract between the material loaders
(:mod:`app.ingestion.loader`) and the knowledge base store
(:mod:`app.kb.store`). They intentionally contain no persistence or embedding
logic so they can be imported and validated without a database connection.
"""

from enum import Enum
from hashlib import sha256

from pydantic import (
    BaseModel,
    Field,
)


class SourceType(str, Enum):
    """Category of an approved knowledge base material.

    Attributes:
        FAQ: Frequently asked questions.
        SCHEDULE: Session, cohort, or deadline schedules.
        ONBOARDING: Onboarding notes and getting-started material.
        PROGRAM_DOC: General program documentation.
    """

    FAQ = "faq"
    SCHEDULE = "schedule"
    ONBOARDING = "onboarding"
    PROGRAM_DOC = "program_doc"


def normalize_content(text: str) -> str:
    """Normalize document text for stable hashing and chunking.

    Line endings are unified and trailing whitespace stripped so that a
    cosmetically changed but semantically identical document produces the same
    content hash and is therefore treated as unchanged on re-ingest.

    Args:
        text: Raw material text.

    Returns:
        The normalized text.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    return "\n".join(lines).strip()


def compute_content_hash(text: str) -> str:
    """Compute a stable SHA-256 hash of normalized material text.

    Args:
        text: Raw material text (normalized before hashing).

    Returns:
        Hex-encoded SHA-256 digest used as the idempotency key.
    """
    return sha256(normalize_content(text).encode("utf-8")).hexdigest()


class SourceMetadata(BaseModel):
    """Provenance metadata attached to every raw material and chunk.

    Attributes:
        title: Human-readable title of the source document.
        source: Stable origin identifier (for example a file path or URL).
        type: The :class:`SourceType` category of the material.
        cohort: Cohort the material belongs to; enforces per-cohort isolation.
    """

    title: str
    source: str
    type: SourceType
    cohort: str


class RawMaterial(BaseModel):
    """A single approved document before chunking.

    Attributes:
        metadata: Provenance metadata for the document.
        content: Full text content of the document.
    """

    metadata: SourceMetadata
    content: str

    @property
    def source_id(self) -> str:
        """Return the stable identity used for update-not-duplicate logic.

        The cohort and source are combined so the same file re-ingested for the
        same cohort replaces its previous chunks, while the same file used by
        two different cohorts stays isolated.
        """
        return f"{self.metadata.cohort}::{self.metadata.source}"

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the normalized content (idempotency key)."""
        return compute_content_hash(self.content)


class KnowledgeChunk(BaseModel):
    """A chunk of a document ready to be embedded and stored.

    Every chunk carries the four required metadata fields (title, source, type,
    cohort) via :attr:`metadata` so provenance survives retrieval.

    Attributes:
        metadata: Provenance metadata inherited from the parent material.
        source_id: Stable identity of the parent material.
        content_hash: Hash of the parent material's content.
        chunk_index: Zero-based position of this chunk within the document.
        content: The chunk text.
    """

    metadata: SourceMetadata
    source_id: str
    content_hash: str
    chunk_index: int = Field(ge=0)
    content: str


class IngestionStats(BaseModel):
    """Summary of a single ingestion run.

    Attributes:
        sources_seen: Number of materials passed to the store.
        sources_ingested: Materials that were new or changed and (re)written.
        sources_skipped: Materials unchanged since the last ingest (no-op).
        chunks_written: Total chunks written across all ingested materials.
    """

    sources_seen: int = 0
    sources_ingested: int = 0
    sources_skipped: int = 0
    chunks_written: int = 0