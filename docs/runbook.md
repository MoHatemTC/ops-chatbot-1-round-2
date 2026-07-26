# Operational Runbook — Operations Support Agent

Step-by-step response procedures for common production issues.

---

## P1 — API not responding

**Symptoms:** Requests time out or return 5xx errors.

**Steps:**

1. Check container status:

```bash
make docker-logs
```

2. Restart the API container:

```bash
make docker-down
make docker-up
```

3. If the database is unreachable, check `POSTGRES_*` env vars and confirm PostgreSQL is running.

4. If the issue persists, check the Prometheus dashboard for error rate spikes at `http://localhost:9090`.

---

## P2 — Agent refusing all answers (confidence gate)

**Symptoms:** Every query returns the honest-refusal message. Logs show `grounded_answer_confidence_gate_refused` repeatedly.

**Steps:**

1. Check the confidence score in logs — look for `score` field in `grounded_answer_confidence_gate_refused` events.

2. If score is near zero, the KB may be empty or the cohort may be wrong:

```sql
SELECT COUNT(*), cohort FROM knowledge_chunks GROUP BY cohort;
```

3. If the KB has data but scores are low, re-run ingestion to refresh embeddings:

```bash
python -m uv run python -m app.kb.ingest --cohort <cohort-id> --source <materials-dir>
```

4. Run evals to confirm scores recover:

```bash
make eval-quick
```

**Do not lower the confidence threshold** without running evals first — it will allow hallucinated answers.

---

## P3 — Cohort leakage warnings

**Symptoms:** Logs show `cohort_leakage_blocked` events. Metric `kb_cohort_leakage_blocked_total` is rising.

**Steps:**

1. Identify which cohort is leaking:

```bash
# Check logs for "actual" field in cohort_leakage_blocked events
make docker-logs | grep cohort_leakage_blocked
```

2. Find incorrectly stored chunks in the database:

```sql
SELECT source_id, cohort, COUNT(*)
FROM knowledge_chunks
GROUP BY source_id, cohort
ORDER BY source_id;
```

3. Delete incorrectly stored chunks:

```sql
DELETE FROM knowledge_chunks
WHERE source_id LIKE '<wrong-cohort>%'
  AND cohort != '<expected-cohort>';
```

4. Re-run ingestion for the affected cohort with the correct cohort ID.

---

## P4 — Escalation tickets not being created

**Symptoms:** Learner queries that should escalate are not creating tickets. Logs show `escalate_node` running but no ticket ID.

**Steps:**

1. Check escalation service logs for errors:

```bash
make docker-logs | grep escalation
```

2. Confirm the escalation contract endpoint is reachable.

3. Check `session_ticket_links_total` metric — if status is `missing_ticket_id`, the escalation service accepted the request but returned no ticket ID.

4. Escalate to the escalation lane owner — this is outside the KB/retrieval lane scope.

---

## P5 — Stale answers after materials update

**Symptoms:** Learners are getting answers from old policy or syllabus versions after an update was ingested.

**Steps:**

1. Confirm the new version was ingested:

```sql
SELECT source_id, content_hash, COUNT(*)
FROM knowledge_chunks
WHERE cohort = '<cohort-id>'
  AND source_id LIKE '%<source-name>%'
GROUP BY source_id, content_hash;
```

If you see two rows with different `content_hash` values, the old version was not cleaned up.

2. Manually remove the stale version:

```sql
DELETE FROM knowledge_chunks
WHERE source_id = '<source-id>'
  AND content_hash = '<old-hash>';
```

3. Re-run ingestion to confirm idempotency:

```bash
python -m uv run python -m app.kb.ingest --cohort <cohort-id> --source <file-path>
```

---

## P6 — LLM provider errors

**Symptoms:** Logs show `grounded_answer_llm_failed`. Answers fall back to honest refusal.

**Steps:**

1. Check `OPENAI_API_KEY` is valid and not expired.

2. Check OpenAI status page for outages.

3. The LLM service has built-in retries with exponential backoff — wait a few minutes before escalating.

4. If the issue persists, check `llm_inference_duration_seconds` in Prometheus for timeout spikes.

---

## Escalation contacts

| Issue type                  | Contact                              |
| --------------------------- | ------------------------------------ |
| KB / retrieval / grounding  | KB & Retrieval lane owner            |
| Escalation tickets          | Escalation lane owner                |
| Infrastructure / Docker     | Platform team                        |
| LLM provider                | OpenAI support + platform team       |
| Business priorities / scope | Internship coordinator (Nadeen Diaa) |
