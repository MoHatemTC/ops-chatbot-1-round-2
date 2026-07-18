"""Data contracts describing a learner's progress within a cohort.

This module defines the canonical shape of "learner progress" data that
feeds the at-risk signal detector (see ``app.risk.signals``). It is
intentionally decoupled from the signal-computation logic: anything that
can produce a ``LearnerProgress`` instance (a DB query, a batch ETL job,
a test fixture) can be fed into the risk engine without changes to either
side.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, computed_field, field_validator


class FeedbackEntry(BaseModel):
    """A single piece of learner-submitted feedback (e.g. a session or task rating)."""

    score: float = Field(..., ge=0, le=5, description="Feedback score on a 0-5 scale (5 = most positive).")
    submitted_at: datetime = Field(..., description="UTC timestamp the feedback was submitted.")

    @field_validator("submitted_at")
    @classmethod
    def _ensure_timezone_aware(cls, value: datetime) -> datetime:
        """Normalize naive datetimes to UTC so downstream comparisons are safe."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class LearnerProgress(BaseModel):
    """Snapshot of a single learner's progress at a point in time.

    This is the sole input to the at-risk signal detector. Every field is
    something we can compute from platform data (tasks, sessions,
    feedback) without any inference or LLM involvement, so the risk
    detector stays deterministic and auditable.
    """

    learner_id: str = Field(..., description="Unique identifier of the learner.")
    cohort_id: str = Field(..., description="Cohort the learner belongs to.")
    as_of: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp this snapshot was computed at.",
    )

    total_tasks: int = Field(..., ge=0, description="Total tasks assigned to the learner so far.")
    completed_tasks: int = Field(..., ge=0, description="Tasks the learner has completed.")
    missed_deadlines: int = Field(default=0, ge=0, description="Count of task/project deadlines missed to date.")

    last_active_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the learner's last recorded activity, if any.",
    )

    recent_feedback: list[FeedbackEntry] = Field(
        default_factory=list,
        description="Feedback entries submitted by the learner, most relevant window only "
        "(callers are expected to pre-filter to a relevant lookback period).",
    )

    @field_validator("last_active_at")
    @classmethod
    def _ensure_timezone_aware(cls, value: datetime | None) -> datetime | None:
        """Normalize naive datetimes to UTC so downstream comparisons are safe."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("completed_tasks")
    @classmethod
    def _completed_not_over_total(cls, value: int, info) -> int:
        """Guard against malformed input where completed exceeds assigned."""
        total = info.data.get("total_tasks")
        if total is not None and value > total:
            raise ValueError("completed_tasks cannot exceed total_tasks")
        return value

    @computed_field  # type: ignore[misc]
    @property
    def progress_ratio(self) -> float:
        """Fraction of assigned tasks completed, in ``[0, 1]``.

        Returns ``1.0`` when no tasks have been assigned yet, since there is
        nothing outstanding to be behind on.
        """
        if self.total_tasks == 0:
            return 1.0
        return self.completed_tasks / self.total_tasks

    @computed_field  # type: ignore[misc]
    @property
    def days_inactive(self) -> float | None:
        """Days elapsed between ``last_active_at`` and ``as_of``.

        Returns ``None`` when there is no recorded activity at all.
        """
        if self.last_active_at is None:
            return None
        delta = self.as_of - self.last_active_at
        return max(delta.total_seconds() / 86400, 0.0)

    @computed_field  # type: ignore[misc]
    @property
    def average_feedback_score(self) -> float | None:
        """Mean of ``recent_feedback`` scores, or ``None`` if there is none."""
        if not self.recent_feedback:
            return None
        return sum(entry.score for entry in self.recent_feedback) / len(self.recent_feedback)
