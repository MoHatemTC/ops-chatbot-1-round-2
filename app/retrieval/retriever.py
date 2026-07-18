"""Cohort-scoped semantic retrieval for approved Operations materials.

The write side of the knowledge base lives in the ingestion lane and stores
embedded chunks in the 'knowledge_chunks' pgvector table. This module
implements the read side used by grounded answering:

1. validate and normalize the learner query;
2. embed it with the same embedding model used during ingestion;
3. run a cosine-distance search against 'knowledge_chunks';
4. enforce cohort isolation;
5. discard weak matches; and
6. return typed chunks with complete source metadata.

Retrieval fails closed. If embedding generation or database search fails, the
public API returns an empty list and logs the internal error. The answer node
can then produce the required honest refusal instead of answering without
approved evidence.
"""

import asyncio
import os
from functools import lru_cache
from typing import Protocol

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
)
from sqlalchemy import (
    Engine,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.config import settings
from app.core.logging import logger

_TABLE_NAME = "knowledge_chunks"
TOP_K = 5
MIN_SIMILARITY = 0.35
_MAX_TOP_K = 20
_CANDIDATE_MULTIPLIER = 3


class RetrievedChunk(BaseModel):
    """A knowledge-base chunk returned by semantic search.

    Attributes:
        source_id: Stable identity of the parent source, including its cohort.
        title: Human-readable title shown in source attribution.
        source: Original file path or URL of the approved material.
        source_type: Material category, such as 'faq' or 'schedule'.
        cohort: Cohort that owns this source.
        content_hash: Hash of the source version used during ingestion.
        chunk_index: Zero-based position of this chunk in its source.
        content: Retrieved text supplied to the grounded-answer prompt.
        distance: Raw pgvector cosine distance; lower is better.
        similarity: '1 - distance'; higher is better.
    """

    source_id: str
    title: str
    source: str
    source_type: str
    cohort: str
    content_hash: str
    chunk_index: int = Field(ge=0)
    content: str
    distance: float = Field(ge=0.0)
    similarity: float = Field(ge=-1.0, le=1.0)

    @property
    def citation_id(self) -> str:
        """Return a deterministic citation identifier for this exact chunk."""
        return f"{self.source_id}#chunk-{self.chunk_index}"


class QueryEmbedder(Protocol):
    """Dependency boundary for converting a query into an embedding vector."""

    def embed_query(self, query: str) -> list[float]:
        """Embed one normalized learner query."""
        ...


class ChunkSearchRepository(Protocol):
    """Dependency boundary for searching stored knowledge chunks."""

    def search(
        self,
        query_embedding: list[float],
        *,
        cohort: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        """Return nearest chunks for one cohort, ordered best first."""
        ...


class OpenAIQueryEmbedder:
    """Query embedder matching the ingestion lane's OpenAI embedding setup."""

    def __init__(self, model: str | None = None) -> None:
        """Initialize the LangChain embedding client."""
        from langchain_openai import OpenAIEmbeddings

        embedding_model = model or settings.LONG_TERM_MEMORY_EMBEDDER_MODEL
        api_key = SecretStr(settings.OPENAI_API_KEY)
        base_url = os.getenv("OPENAI_BASE_URL")

        if base_url:
            self._client = OpenAIEmbeddings(
                model=embedding_model,
                api_key=api_key,
                base_url=base_url,
            )
        else:
            self._client = OpenAIEmbeddings(
                model=embedding_model,
                api_key=api_key,
            )

    def embed_query(self, query: str) -> list[float]:
        """Generate one embedding vector for a learner query."""
        return self._client.embed_query(query)


def _to_vector_literal(embedding: list[float]) -> str:
    """Render a numeric vector as a pgvector literal like '[1,2,3]'."""
    if not embedding:
        raise ValueError("query embedding must not be empty")
    return "[" + ",".join(repr(value) for value in embedding) + "]"


class PgVectorChunkSearchRepository:
    """Search the 'knowledge_chunks' table with cosine distance."""

    def __init__(self, engine: Engine) -> None:
        """Store the shared SQLAlchemy engine.

        The retriever intentionally does not create or migrate the table.
        The ingestion lane owns that schema and must run before retrieval.
        """
        self._engine = engine

    def search(
        self,
        query_embedding: list[float],
        *,
        cohort: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        """Return nearest chunks from the requested cohort.

        'embedding <=> query' is pgvector cosine distance. It is computed once
        in a subquery so ordering and returned metadata use the same value.
        Parameter binding is used for all user-controlled values.
        """
        statement = text(f"""
            SELECT
                source_id,
                cohort,
                title,
                source,
                type AS source_type,
                content_hash,
                chunk_index,
                content,
                distance
            FROM (
                SELECT
                    source_id,
                    cohort,
                    title,
                    source,
                    type,
                    content_hash,
                    chunk_index,
                    content,
                    embedding <=> CAST(:query_embedding AS vector) AS distance
                FROM {_TABLE_NAME}
                WHERE cohort = :cohort
                  AND embedding IS NOT NULL
            ) AS ranked_chunks
            ORDER BY distance ASC
            LIMIT :limit
            """)

        with Session(self._engine) as session:
            rows = session.execute(
                statement,
                {
                    "query_embedding": _to_vector_literal(query_embedding),
                    "cohort": cohort,
                    "limit": limit,
                },
            ).mappings()

            chunks: list[RetrievedChunk] = []
            for row in rows:
                distance = float(row["distance"])
                chunks.append(
                    RetrievedChunk(
                        source_id=str(row["source_id"]),
                        title=str(row["title"]),
                        source=str(row["source"]),
                        source_type=str(row["source_type"]),
                        cohort=str(row["cohort"]),
                        content_hash=str(row["content_hash"]),
                        chunk_index=int(row["chunk_index"]),
                        content=str(row["content"]),
                        distance=distance,
                        similarity=1.0 - distance,
                    )
                )

        return chunks


class KnowledgeRetriever:
    """Orchestrate safe query embedding, vector search, and score filtering."""

    def __init__(
        self,
        repository: ChunkSearchRepository,
        embedder: QueryEmbedder,
        *,
        min_similarity: float = MIN_SIMILARITY,
    ) -> None:
        """Initialize the retriever with injectable dependencies.

        Args:
            repository: Search backend for stored chunks.
            embedder: Query embedding provider.
            min_similarity: Minimum cosine similarity accepted as evidence.
                This initial value must be calibrated with the real corpus and
                evaluation set before production rollout.

        Raises:
            ValueError: If 'min_similarity' is outside the cosine-similarity
                range accepted by this application.
        """
        if not 0.0 <= min_similarity <= 1.0:
            raise ValueError("min_similarity must be between 0.0 and 1.0")

        self._repository = repository
        self._embedder = embedder
        self._min_similarity = min_similarity

    def retrieve_sync(
        self,
        query: str,
        *,
        cohort: str,
        top_k: int = TOP_K,
    ) -> list[RetrievedChunk]:
        """Retrieve relevant approved chunks synchronously.

        Empty queries or cohorts return no evidence. External failures also
        return an empty list so the grounded-answer layer refuses safely.

        Args:
            query: Learner question to search for.
            cohort: Mandatory cohort filter preventing cross-cohort leakage.
            top_k: Maximum number of accepted chunks to return.

        Returns:
            Relevant chunks ordered from highest to lowest similarity.

        Raises:
            ValueError: If 'top_k' is outside the supported range.
        """
        normalized_query = " ".join(query.split())
        normalized_cohort = cohort.strip()
        if not normalized_query or not normalized_cohort:
            return []
        if not 1 <= top_k <= _MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {_MAX_TOP_K}")

        candidate_limit = min(top_k * _CANDIDATE_MULTIPLIER, _MAX_TOP_K)

        try:
            query_embedding = self._embedder.embed_query(normalized_query)
            candidates = self._repository.search(
                query_embedding,
                cohort=normalized_cohort,
                limit=candidate_limit,
            )
        except (SQLAlchemyError, ValueError) as exc:
            logger.exception(
                "knowledge_retrieval_failed",
                cohort=normalized_cohort,
                error=str(exc),
            )
            return []
        except Exception as exc:
            # Embedding clients can raise provider-specific exception classes.
            # Failing closed is safer than allowing an ungrounded answer.
            logger.exception(
                "knowledge_embedding_failed",
                cohort=normalized_cohort,
                error=str(exc),
            )
            return []

        accepted = [chunk for chunk in candidates if chunk.similarity >= self._min_similarity]
        accepted.sort(key=lambda chunk: chunk.similarity, reverse=True)

        # The query already filters by cohort, but this defense-in-depth check
        # prevents a faulty custom repository from leaking another cohort.
        scoped = [chunk for chunk in accepted if chunk.cohort == normalized_cohort]
        results = scoped[:top_k]

        logger.info(
            "knowledge_retrieval_completed",
            cohort=normalized_cohort,
            candidates=len(candidates),
            accepted=len(results),
            min_similarity=self._min_similarity,
        )
        return results

    async def retrieve(
        self,
        query: str,
        *,
        cohort: str,
        top_k: int = TOP_K,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks without blocking LangGraph's event loop."""
        return await asyncio.to_thread(
            self.retrieve_sync,
            query,
            cohort=cohort,
            top_k=top_k,
        )


def build_default_retriever() -> KnowledgeRetriever:
    """Build the production retriever from shared application services."""
    from app.services.database import database_service

    repository = PgVectorChunkSearchRepository(database_service.engine)
    embedder = OpenAIQueryEmbedder()
    return KnowledgeRetriever(repository=repository, embedder=embedder)


@lru_cache(maxsize=1)
def get_retriever() -> KnowledgeRetriever:
    """Return a lazily constructed process-wide production retriever."""
    return build_default_retriever()


async def retrieve(
    query: str,
    *,
    cohort: str,
    top_k: int = TOP_K,
) -> list[RetrievedChunk]:
    """Convenience API used by the grounded-answer LangGraph node."""
    return await get_retriever().retrieve(query, cohort=cohort, top_k=top_k)
