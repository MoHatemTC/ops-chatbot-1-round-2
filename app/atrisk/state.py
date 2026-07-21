"""Persistence layer for at-risk state — the auditable, shared risk contract (PRD F2.3).

Every detector run upserts one AtRiskStateRecord per (learner_id, run_date).
Re-running the job for the same day always converges on the same row
instead of inserting duplicates, which is what makes the job idempotent
from the persistence side. Nothing here is ever deleted or overwritten
across days, so the table doubles as the audit trail Ops/dashboards can
query for trend history — the same "shared risk contract" both the
scheduled job and the Ops dashboards read from.

Follows the same pattern as app/notifications/service.py: a fresh
DatabaseService() per call, reserve-then-commit against a DB-level unique
constraint, and fall back to an update path if a concurrent run wins the
insert race.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from pydantic import BaseModel as SchemaBaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, UniqueConstraint, select

from app.atrisk.detector import DetectionResult
from app.models.base import BaseModel as ORMBaseModel
from app.services.database import DatabaseService


class AtRiskStateRecord(ORMBaseModel, table=True):
    """One auditable snapshot of a learner's at-risk evaluation for one day.

    Attributes:
        id: Primary key.
        learner_id: The learner this record is for.
        run_date: Calendar date (UTC) the detector ran for. Combined with
            learner_id, this is the idempotency key — re-running the
            detector job for the same day updates this row instead of
            inserting a duplicate.
        at_risk: Overall verdict for this run.
        score: Number of individual signals tripped (0-4).
        missed_deadlines: Whether the missed-deadlines signal tripped.
        inactive: Whether the inactivity signal tripped.
        low_progress: Whether the low-progress signal tripped.
        low_feedback: Whether the low-feedback signal tripped.
        thresholds_json: The RiskThresholds used for this evaluation,
            JSON-encoded, so the record stays self-describing even if
            defaults change later.
        evaluated_at: Exact timestamp the evaluation ran.
        created_at: Inherited from BaseModel — when this row was first written.
    """

    __table_args__ = (UniqueConstraint("learner_id", "run_date", name="uq_atriskstaterecord_learner_rundate"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    learner_id: str = Field(index=True)
    run_date: date = Field(index=True)
    at_risk: bool
    score: int
    missed_deadlines: bool
    inactive: bool
    low_progress: bool
    low_feedback: bool
    thresholds_json: str
    evaluated_at: datetime


class AtRiskAggregate(SchemaBaseModel):
    """Read-only aggregate of at-risk state for one run_date, for Ops dashboards (PRD F3.3)."""

    run_date: date
    total_learners: int
    at_risk_count: int
    at_risk_percent: float
    missed_deadlines_count: int
    inactive_count: int
    low_progress_count: int
    low_feedback_count: int


def _existing_record(session, learner_id: str, run_date: date) -> Optional[AtRiskStateRecord]:
    """Look up the record for one learner + run_date, if any."""
    return session.exec(
        select(AtRiskStateRecord).where(
            AtRiskStateRecord.learner_id == learner_id,
            AtRiskStateRecord.run_date == run_date,
        )
    ).first()


def upsert_at_risk_state(result: DetectionResult, run_date: Optional[date] = None) -> AtRiskStateRecord:
    """Persist one learner's detection result as an auditable state record.

    Idempotent: re-running the detector for the same learner_id + run_date
    updates that day's record in place rather than inserting a duplicate.
    This is what lets app/jobs/atrisk_job.py be safely re-run or retried
    (e.g. after a transient failure) without corrupting the audit trail
    with duplicate rows for the same day.

    Args:
        result: The detection result to persist.
        run_date: The calendar date this run counts as. Defaults to the
            date portion of result.evaluated_at.

    Returns:
        The persisted (inserted or updated) AtRiskStateRecord.
    """
    effective_run_date = run_date or result.evaluated_at.date()
    signals = result.signals

    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        record = _existing_record(session, result.learner_id, effective_run_date)

        if record is None:
            record = AtRiskStateRecord(
                learner_id=result.learner_id,
                run_date=effective_run_date,
                at_risk=signals.at_risk,
                score=signals.score,
                missed_deadlines=signals.missed_deadlines,
                inactive=signals.inactive,
                low_progress=signals.low_progress,
                low_feedback=signals.low_feedback,
                thresholds_json=result.thresholds.model_dump_json(),
                evaluated_at=result.evaluated_at,
            )
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
                return record
            except IntegrityError:
                # A concurrent run of this same job won the insert race —
                # fall through and update that row instead.
                session.rollback()
                record = _existing_record(session, result.learner_id, effective_run_date)

        # Update path: either the record already existed, or we just lost
        # the insert race above. Either way, make it reflect this evaluation.
        record.at_risk = signals.at_risk
        record.score = signals.score
        record.missed_deadlines = signals.missed_deadlines
        record.inactive = signals.inactive
        record.low_progress = signals.low_progress
        record.low_feedback = signals.low_feedback
        record.thresholds_json = result.thresholds.model_dump_json()
        record.evaluated_at = result.evaluated_at
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_latest_state(learner_id: str) -> Optional[AtRiskStateRecord]:
    """Return a learner's most recent at-risk state record, if any."""
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        return session.exec(
            select(AtRiskStateRecord)
            .where(AtRiskStateRecord.learner_id == learner_id)
            .order_by(AtRiskStateRecord.run_date.desc())
        ).first()


def get_history(learner_id: str, limit: int = 30) -> list[AtRiskStateRecord]:
    """Return a learner's at-risk history, most recent first — the audit trail."""
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        rows = session.exec(
            select(AtRiskStateRecord)
            .where(AtRiskStateRecord.learner_id == learner_id)
            .order_by(AtRiskStateRecord.run_date.desc())
            .limit(limit)
        ).all()
        return list(rows)


def get_latest_run_date() -> Optional[date]:
    """Return the most recent run_date with any persisted state, if any."""
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        return session.exec(select(AtRiskStateRecord.run_date).order_by(AtRiskStateRecord.run_date.desc())).first()


def get_aggregate(run_date: Optional[date] = None) -> AtRiskAggregate:
    """Read-only aggregate of at-risk state for one run_date, for Ops dashboards.

    Defaults to the most recent run_date with any persisted state.

    Args:
        run_date: The date to aggregate. Defaults to the latest available.

    Returns:
        AtRiskAggregate with totals and a per-signal breakdown. All counts
        are zero if no state has been persisted yet.
    """
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        target_date = run_date or get_latest_run_date()
        if target_date is None:
            return AtRiskAggregate(
                run_date=datetime.now(UTC).date(),
                total_learners=0,
                at_risk_count=0,
                at_risk_percent=0.0,
                missed_deadlines_count=0,
                inactive_count=0,
                low_progress_count=0,
                low_feedback_count=0,
            )

        records = session.exec(select(AtRiskStateRecord).where(AtRiskStateRecord.run_date == target_date)).all()
        total = len(records)
        at_risk_count = sum(1 for r in records if r.at_risk)

        return AtRiskAggregate(
            run_date=target_date,
            total_learners=total,
            at_risk_count=at_risk_count,
            at_risk_percent=round((at_risk_count / total * 100), 2) if total else 0.0,
            missed_deadlines_count=sum(1 for r in records if r.missed_deadlines),
            inactive_count=sum(1 for r in records if r.inactive),
            low_progress_count=sum(1 for r in records if r.low_progress),
            low_feedback_count=sum(1 for r in records if r.low_feedback),
        )


def get_at_risk_learner_ids(run_date: Optional[date] = None) -> list[str]:
    """Read-only: learner_ids flagged at_risk for a given run_date (defaults to latest)."""
    db_service = DatabaseService()
    with db_service.get_session_maker() as session:
        target_date = run_date or get_latest_run_date()
        if target_date is None:
            return []
        rows = session.exec(
            select(AtRiskStateRecord.learner_id).where(
                AtRiskStateRecord.run_date == target_date,
                AtRiskStateRecord.at_risk == True,  # noqa: E712 -- SQLAlchemy column comparison, not a Python bool check
            )
        ).all()
        return list(rows)
