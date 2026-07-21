"""Data contract describing a learner's progress snapshot."""

from datetime import datetime

from pydantic import BaseModel, Field


class LearnerProgress(BaseModel):
    """Progress snapshot for a learner, used as input to the at-risk detector.

    Attributes:
        learner_id: Unique identifier of the learner this snapshot belongs to.
        missed_deadlines: Count of task/project deadlines missed to date. Must be >= 0.
        inactive_days: Days since the learner's last recorded activity. Must be >= 0.
        progress_percent: Overall completion percentage for the learner's assigned
            work, on a 0-100 scale. Defaults to 100 (fully caught up) when unknown.
        feedback_score: Most recent feedback score the learner gave, on a 1-5 scale
            (5 = most positive). None means the learner hasn't left feedback yet —
            this is treated as "no signal," not as a low score.
        evaluated_at: Timestamp this snapshot was computed at.
    """

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