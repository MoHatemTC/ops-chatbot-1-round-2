"""Ops Console KB admin API — re-ingest, list, and retire knowledge base materials."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.kb.store import build_default_store
from app.models.user import User
from app.schemas.knowledge import IngestionStats, RawMaterial

router = APIRouter()


@router.post("/reingest", response_model=IngestionStats)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def reingest_materials(
    request: Request,
    materials: list[RawMaterial],
    user: User = Depends(get_current_user),
):
    """Re-ingest a batch of approved materials into the knowledge base.

    Delegates to KBStore.ingest, which is update-not-duplicate: unchanged
    materials (matching content hash) are skipped automatically.

    Args:
        request: The FastAPI request object for rate limiting.
        materials: The approved documents to ingest.
        user: The authenticated user performing the ingestion.

    Returns:
        IngestionStats: Counts of sources seen/ingested/skipped and chunks written.
    """
    try:
        store = build_default_store()
        stats = store.ingest(materials)

        logger.info(
            "kb_reingest_completed",
            user_id=user.id,
            sources_seen=stats.sources_seen,
        )

        return stats

    except Exception as e:
        logger.exception(
            "kb_reingest_failed",
            user_id=user.id,
            error=str(e),
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.get("/materials")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def list_materials(
    request: Request,
    user: User = Depends(get_current_user),
):
    """List all knowledge base materials.

    This endpoint is intentionally left unimplemented until the KBStore
    interface exposes a public list_materials() method.
    """
    logger.warning(
        "kb_list_not_implemented",
        user_id=user.id,
    )

    raise HTTPException(
        status_code=501,
        detail=(
            "Listing KB materials is not implemented. "
            "The current KBStore interface does not support this operation."
        ),
    )


@router.post("/retire/{material_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def retire_material(
    request: Request,
    material_id: str,
    user: User = Depends(get_current_user),
):
    """Retire a knowledge base material.

    This endpoint is intentionally left unimplemented until the KBStore
    interface exposes a public retire_material() method.
    """
    logger.warning(
        "kb_retire_not_implemented",
        user_id=user.id,
        material_id=material_id,
    )

    raise HTTPException(
        status_code=501,
        detail=(
            "Retiring KB materials is not implemented. "
            "The current KBStore interface does not support this operation."
        ),
    )