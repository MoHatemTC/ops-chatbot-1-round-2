# At-Risk Detector Job & Proactive Learner Nudges

Implements PRD F2.3-F2.5: a scheduled at-risk detector, an auditable
persisted risk state, deduplicated proactive nudges, and read-only
aggregates for Ops dashboards.

## Files

| File | Responsibility |
| --- | --- |
| `app/schemas/signals.py` | **Fixed** — was a broken Week-1 draft (syntax errors, missing return). Now a working `compute_risk_signals`. |
| `app/atrisk/detector.py` | Pure threshold evaluation. No I/O. `resolve_thresholds` supports per-learner overrides. |
| `app/atrisk/state.py` | SQLModel table `AtRiskStateRecord` + persistence/aggregate functions — the auditable, shared risk contract. |
| `app/atrisk/nudges.py` | Abstract `NotificationSender` contract, dedup/frequency-capped nudge building, delivery via the existing notification service. |
| `app/jobs/atrisk_job.py` | Orchestrates detect -> persist -> nudge as one idempotent job run. |
| `evals/atrisk_suite.py` | Labeled-dataset precision/recall/F1 report for the detector. |
| `tests/test_atrisk.py` | Pytest coverage (detector, state idempotency, nudge dedup, end-to-end job idempotency). |
| `alembic/versions/d4b7f2a91c3e_*.py` + `alembic/env.py` | New migration for the `atriskstaterecord` table (required — a new SQLModel table needs a migration to exist in Postgres). |

## Idempotency model

- **Detection** is a pure function of its inputs — running it twice on the
  same `LearnerProgress` always yields the same `AtRiskSignals`.
- **State persistence** upserts on `(learner_id, run_date)` — a DB-level
  unique constraint (`uq_atriskstaterecord_learner_rundate`) backs this, so
  even two concurrent job runs can't create duplicate rows for the same
  day (the loser of the insert race falls back to an update).
- **Nudge delivery** reuses the existing `dedup_key` + `tenacity` retry
  machinery in `app/notifications/service.py` / `app/scheduler/runner.py`.
  The dedup key is bucketed by a configurable frequency window (default 7
  days), so a learner who stays at-risk across daily runs gets nudged once
  per window, not once per run — that's the F2.4 frequency cap.

  **Known limitation:** the bucket is aligned to the epoch, not to each
  learner's first nudge, so two nudges can land as little as one day apart
  if they straddle a bucket boundary. This guarantees "at most one nudge
  per 7-day bucket," not a strict rolling "at least 7 days since the last
  nudge." Verified with a 30-day sweep: buckets never span more than 7
  consecutive days, but a boundary can still produce a short gap. If a
  strict rolling cap is required, swap `_nudge_period_bucket` for a lookup
  against the learner's most recent `SENT` `AT_RISK_NUDGE` notification.

## What still needs wiring before this runs against real data

1. **A `ProgressProvider`** — `app/jobs/atrisk_job.run_at_risk_job` takes a
   callable returning `list[LearnerProgress]`. Nothing in the codebase yet
   computes real learner progress (no progress-data model/service exists),
   so that's intentionally left pluggable rather than guessed at.
2. **A real `NotificationSender`** — defaults to a no-op sender so the job
   never crashes before a channel (email/SMS/push/in-app) is chosen.
   Implement `NotificationSender.send()` for the real channel and pass it
   into `run_at_risk_job(..., sender=...)`.
3. **A scheduler trigger** — `run_at_risk_job` is a plain function; wire it
   into whatever cron/Celery-beat/APScheduler mechanism the project uses to
   run scheduled jobs (`app/scheduler/` currently only holds the
   notification-retry runner, not a cron scheduler).
4. **An Ops-facing API route**, if wanted — `app/atrisk/state.get_aggregate`
   and `get_at_risk_learner_ids` are ready to wrap in a FastAPI endpoint
   under `app/api/v1/`, matching the pattern in `app/api/v1/chatbot.py`.
   Not added here since it wasn't in the assigned file list.

## Running it

```bash
# Apply the new migration
make migrate

# Run the detector precision eval
python -m evals.atrisk_suite

# Run the pytest suite (needs the project's Postgres, e.g. `make docker-up ENV=test`)
pytest tests/test_atrisk.py -v

# Lint/typecheck
make check
```
