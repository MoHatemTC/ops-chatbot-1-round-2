"""Ops Console dashboard API — read-only support metrics for program leads."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from app.observability.kpis import update_support_metrics
from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.dashboards.metrics import get_support_metrics
from app.models.user import User
from app.services.database import DatabaseService

router = APIRouter()
db_service = DatabaseService()


@router.get("/metrics")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["dashboards"][0])
async def get_dashboard_metrics(
    request: Request,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    user: User = Depends(get_current_user),
):
    """Return Phase-1 support metrics for the given time window.

    If start/end are omitted, defaults to the last 7 days.

    Args:
        request: The FastAPI request object for rate limiting.
        start: Start of the reporting window (optional, defaults to 7 days before end).
        end: End of the reporting window (optional, defaults to now).
        user: The authenticated user requesting the metrics.

    Returns:
        dict: support_volume, escalation_rate, and resolution_time (estimate).
    """
    try:
        resolved_end = end or datetime.now(timezone.utc)
        resolved_start = start or (resolved_end - timedelta(days=7))

        with db_service.get_session_maker() as session:
            metrics = get_support_metrics(session, resolved_start, resolved_end)
            update_support_metrics(metrics)
            return metrics
    except Exception as e:
        logger.exception("dashboard_metrics_failed", user_id=user.id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
