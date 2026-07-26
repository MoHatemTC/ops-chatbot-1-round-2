# Admin Guide — Operations Support Agent

Day-to-day operation reference for the platform team.

---

## Starting the system

### Docker (recommended)

```bash
make docker-up       # starts API (port 8000) + PostgreSQL
make docker-migrate  # runs Alembic migrations inside the app container
```

### Local Python

```bash
make migrate  # creates tables via Alembic
make dev      # starts server with hot reload on port 8000
```

Check the API is healthy:

```bash
curl http://localhost:8000/docs
```

---

## Environment variables

Copy `.env.example` to `.env.development` and fill in:

| Variable                   | Required | Description                                               |
| -------------------------- | -------- | --------------------------------------------------------- |
| `OPENAI_API_KEY`           | Yes      | LLM and embedding provider                                |
| `JWT_SECRET_KEY`           | Yes      | Auth token signing                                        |
| `POSTGRES_HOST`            | Yes      | Database host (`localhost` for local, `db` inside Docker) |
| `POSTGRES_PORT`            | Yes      | Default `5432`                                            |
| `POSTGRES_DB`              | Yes      | Database name                                             |
| `POSTGRES_USER`            | Yes      | Database user                                             |
| `POSTGRES_PASSWORD`        | Yes      | Database password                                         |
| `DEFAULT_COHORT`           | Yes      | Fallback cohort when none is set per-user                 |
| `LANGFUSE_TRACING_ENABLED` | No       | Set `false` to disable tracing during development         |
| `LANGFUSE_PUBLIC_KEY`      | No       | Required if tracing is enabled                            |
| `LANGFUSE_SECRET_KEY`      | No       | Required if tracing is enabled                            |

---

## Monitoring

### Logs

```bash
make docker-logs   # tail all container logs
```

Logs are structured JSON. Key events to watch:

| Event                                     | Meaning                                              |
| ----------------------------------------- | ---------------------------------------------------- |
| `knowledge_retrieval_completed`           | Retrieval ran successfully                           |
| `cohort_leakage_blocked`                  | A chunk from the wrong cohort was caught and removed |
| `grounded_answer_confidence_gate_refused` | Answer refused due to low confidence                 |
| `grounded_answer_generated`               | Answer produced successfully with sources            |

### Prometheus metrics

Available at `http://localhost:8000/metrics`. Key metrics:

| Metric                                  | What it tracks                                                      |
| --------------------------------------- | ------------------------------------------------------------------- |
| `kb_cohort_retrieval_total`             | Retrieval attempts by cohort and outcome                            |
| `kb_cohort_leakage_blocked_total`       | Cross-cohort leakage caught by the guard                            |
| `kb_freshness_duplicates_removed_total` | Stale chunks removed per filter run                                 |
| `kb_confidence_decisions_total`         | Confidence gate decisions (sufficient / insufficient / no_evidence) |
| `kb_confidence_score`                   | Distribution of confidence scores                                   |
| `escalation_routing_total`              | Escalation decisions by route and trigger                           |

Open the Grafana dashboard at `http://localhost:3000` when running the full stack (`make stack-up`).

---

## Running quality checks

```bash
make check   # lint (ruff) + typecheck (pyright)
```

Run tests:

```bash
python -m uv run pytest tests/
```

---

## Database migrations

```bash
make migration MSG="describe your change"  # generate a new migration
make migrate                               # apply all pending migrations
make migrate-downgrade                     # roll back the last migration
make migrate-history                       # show migration history
```

Inside Docker:

```bash
make docker-migrate
make docker-migrate-downgrade
```

---

## Troubleshooting

**API not starting**
Check `OPENAI_API_KEY` and `POSTGRES_*` variables are set correctly in your `.env`.

**`could not translate host name "db"`**
Use `POSTGRES_HOST=localhost` when running outside Docker. Inside the container keep `db`.

**Langfuse errors**
Set `LANGFUSE_TRACING_ENABLED=false` in your `.env` to disable tracing.

**Cohort leakage warnings in logs**
If you see `cohort_leakage_blocked` frequently, check the ingestion pipeline — chunks may be stored with the wrong cohort value.

**Confidence gate refusing too many answers**
The default threshold is `0.55`. If too many answers are being refused, check that the KB materials are up to date and re-run ingestion. Do not lower the threshold without running evals first.
