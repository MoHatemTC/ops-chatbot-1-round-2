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
        IngestionStats: counts of sources seen/ingested/skipped and chunks written.
    """
    try:
        store = build_default_store()
        stats = store.ingest(materials)
        logger.info("kb_reingest_completed", user_id=user.id, sources_seen=stats.sources_seen)
        return stats
    except Exception as e:
        logger.exception("kb_reingest_failed", user_id=user.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/materials")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def list_materials(
    request: Request,
    user: User = Depends(get_current_user),
):
    """List ingested knowledge base materials.

    Temporary stub.

    KBStore currently exposes only ``ingest()``. Document listing is not yet
    supported by the underlying storage layer, so this endpoint returns mock
    data until metadata retrieval is implemented.
    """
    logger.info("kb_list_materials_stub_called", user_id=user.id)

    return {
        "materials": [],
        "message": ("Document listing is not yet supported by KBStore. This endpoint is currently a stub."),
    }


@router.post("/materials/{material_id}/retire")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def retire_material(
    request: Request,
    material_id: str,
    user: User = Depends(get_current_user),
):
    """Retire a knowledge base material.

    Temporary stub.

    KBStore currently exposes only ``ingest()``. Material retirement is not yet
    supported by the storage layer, so this endpoint returns a placeholder
    response until deletion support is available.
    """
    logger.info(
        "kb_retire_material_stub_called",
        user_id=user.id,
        material_id=material_id,
    )

    return {
        "material_id": material_id,
        "status": "stub",
        "message": ("Material retirement is not yet supported by KBStore. This endpoint is currently a stub."),
    }
