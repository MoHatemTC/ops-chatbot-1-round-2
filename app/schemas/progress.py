from datetime import datetime

from pydantic import BaseModel, Field

//change
class LearnerProgress(BaseModel):
    """Progress snapshot for a learner."""

    learner_id: str

    missed_deadlines: int = Field(default=0, ge=0)

    inactive_days: int = Field(default=0, ge=0)

    progress_percent: float = Field(default=100, ge=0, le=100)

    feedback_score: float | None = Field(
        default=None,
        ge=1,
        le=5,
    )

    evaluated_at: datetime
