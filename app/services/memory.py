"""Long-term memory service using mem0 and pgvector with cohort isolation support."""

from mem0 import AsyncMemory

from app.core.cache import (
    cache_key,
    cache_service,
)
from app.core.config import settings
from app.core.logging import logger


class MemoryService:
    """Service for managing long-term memory using mem0 and pgvector with cohort scoping."""

    def __init__(self):
        """Initialize the memory service."""
        self._memory: AsyncMemory | None = None

    async def _get_memory(self) -> AsyncMemory:
        if self._memory is None:
            self._memory = await AsyncMemory.from_config(
                config_dict={
                    "vector_store": {
                        "provider": "pgvector",
                        "config": {
                            "collection_name": settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                            "dbname": settings.POSTGRES_DB,
                            "user": settings.POSTGRES_USER,
                            "password": settings.POSTGRES_PASSWORD,
                            "host": settings.POSTGRES_HOST,
                            "port": settings.POSTGRES_PORT,
                        },
                    },
                    "llm": {
                        "provider": "openai",
                        "config": {"model": settings.LONG_TERM_MEMORY_MODEL},
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {"model": settings.LONG_TERM_MEMORY_EMBEDDER_MODEL},
                    },
                }
            )
        return self._memory

    async def initialize(self) -> None:
        """Pre-warm the mem0 AsyncMemory instance and its pgvector connection pool.

        Call once at startup so the first search() or add() doesn't pay the
        ~130ms from_config + pgvector.list_cols() cold-init cost.
        """
        await self._get_memory()
        logger.info("memory_service_initialized")

    async def search(self, user_id: str | None, query: str, cohort_id: str | None = None) -> str:
        """Search relevant memories for a user scoped strictly by cohort_id.

        Checks cache first; on miss, queries mem0 with metadata filtering and caches the result.

        Returns formatted memory string, or empty string on failure or when
        no user_id is supplied.
        """
        if user_id is None:
            return ""
        try:
            # Multi-Cohort Scoped Cache Key to prevent cross-cohort cache hits
            cache_scope = f"{cohort_id}:{user_id}" if cohort_id else str(user_id)
            key = cache_key("memory", cache_scope, query)
            
            cached = await cache_service.get(key)
            if cached is not None:
                logger.debug("memory_search_cache_hit", user_id=user_id, cohort_id=cohort_id)
                return cached

            memory = await self._get_memory()
            
            # Scoped metadata filter to enforce strict isolation in pgvector
            filters = {}
            if cohort_id:
                filters["cohort_id"] = cohort_id

            results = await memory.search(
                user_id=str(user_id), 
                query=query,
                filters=filters if filters else None
            )

            # Verification against cross-cohort leakage
            filtered_results = []
            for r in results.get("results", []):
                rec_cohort = r.get("metadata", {}).get("cohort_id") if isinstance(r, dict) else None
                if cohort_id and rec_cohort and rec_cohort != cohort_id:
                    logger.warning("cross_cohort_leakage_blocked", user_id=user_id, requested_cohort=cohort_id, leaked_cohort=rec_cohort)
                    continue
                filtered_results.append(f"* {r['memory']}")

            result = "\n".join(filtered_results)

            # Cache successful scoped results
            if result:
                await cache_service.set(key, result)

            return result
        except Exception as e:
            logger.error("failed_to_get_relevant_memory", error=str(e), user_id=user_id, cohort_id=cohort_id, query=query)
            return ""

    async def add(self, user_id: str | None, messages: list[dict], metadata: dict | None = None, cohort_id: str | None = None) -> None:
        """Add messages to long-term memory scoped with cohort_id metadata.

        No-op when ``user_id`` is ``None``.
        """
        if user_id is None:
            return
        try:
            memory = await self._get_memory()
            
            # Enforce cohort_id inside metadata payload
            payload_metadata = metadata or {}
            if cohort_id:
                payload_metadata["cohort_id"] = cohort_id

            await memory.add(messages, user_id=str(user_id), metadata=payload_metadata)
            logger.info("long_term_memory_updated_successfully", user_id=user_id, cohort_id=cohort_id)
        except Exception as e:
            logger.exception("failed_to_update_long_term_memory", user_id=user_id, cohort_id=cohort_id, error=str(e))


memory_service = MemoryService()