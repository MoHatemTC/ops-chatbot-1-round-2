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
    """Re-ingest a batch of approved materials into the knowledge base."""
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
    """List all materials currently in the knowledge base, with freshness info."""
    try:
        store = build_default_store()
        materials = store.list_materials()

        logger.info(
            "kb_materials_listed",
            user_id=user.id,
            count=len(materials),
        )

        return {"materials": materials}

    except Exception as e:
        logger.exception(
            "kb_list_failed",
            user_id=user.id,
            error=str(e),
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.post("/retire/{material_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def retire_material(
    request: Request,
    material_id: str,
    user: User = Depends(get_current_user),
):
    """Retire a material from the knowledge base."""
    try:
        store = build_default_store()

        retired = store.retire_material(material_id)

        if not retired:
            raise HTTPException(
                status_code=404,
                detail=f"No material found for material_id={material_id}",
            )

        logger.info(
            "kb_material_retired_via_api",
            user_id=user.id,
            material_id=material_id,
        )

        return {
            "material_id": material_id,
            "retired": True,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(
            "kb_retire_failed",
            user_id=user.id,
            material_id=material_id,
            error=str(e),
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )