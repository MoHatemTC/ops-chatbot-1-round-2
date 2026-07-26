# Materials Update Instructions — Knowledge Base

How to add, update, or remove approved Operations materials from the knowledge base.

---

## Supported material types

| Type          | Examples                                      |
| ------------- | --------------------------------------------- |
| `faq`         | Frequently asked questions                    |
| `policy`      | Attendance, submission, conduct policies      |
| `syllabus`    | Course syllabus per cohort                    |
| `program_doc` | Program overview, onboarding notes, schedules |

---

## Adding new materials

1. Prepare the source file (Markdown, PDF, or plain text).
2. Place it in the ingestion input directory for the correct cohort.
3. Run the ingestion pipeline:

```bash
python -m uv run python -m app.kb.ingest --cohort <cohort-id> --source <file-path>
```

4. Verify the material was indexed:

```bash
# Check logs for "knowledge_ingestion_completed"
make docker-logs
```

---

## Updating existing materials

The ingestion pipeline uses **update-not-duplicate semantics** — running it again on an updated file replaces the old version automatically. No manual cleanup needed.

1. Edit or replace the source file.
2. Re-run ingestion with the same cohort and source path:

```bash
python -m uv run python -m app.kb.ingest --cohort <cohort-id> --source <file-path>
```

**How it works internally:**

- The pipeline computes a `content_hash` for the new file.
- If the hash matches what is stored, the file is skipped (no change).
- If the hash differs, the old chunks are deleted and new chunks are inserted in a single transaction — no duplicates, no partial states.
- The freshness filter (`app/kb/freshness.py`) ensures only the latest version is used in answers.

---

## Removing materials

To remove a source from the knowledge base, delete its chunks from the database directly:

```sql
DELETE FROM knowledge_chunks
WHERE source_id = '<cohort>::<source-path>'
  AND cohort = '<cohort-id>';
```

Then confirm removal by checking the logs for retrieval — the source should no longer appear in answers.

---

## Cohort isolation

Every material belongs to exactly one cohort. When ingesting, always pass the correct `--cohort` flag. Materials stored under the wrong cohort will never appear in answers for other cohorts — the retrieval boundary rejects them — but they will waste storage.

To list materials per cohort:

```sql
SELECT DISTINCT source_id, title, type, cohort
FROM knowledge_chunks
WHERE cohort = '<cohort-id>'
ORDER BY title;
```

---

## Verifying the update

After ingestion, run the evals suite to confirm grounding and faithfulness scores are stable:

```bash
make eval-quick
```

If scores drop after an update, review the new material for ambiguous or conflicting content.

---

## Checklist

- [ ] Material reviewed and approved by Ops before ingestion
- [ ] Correct cohort ID used
- [ ] Ingestion ran without errors (check logs)
- [ ] Evals scores stable after update
- [ ] Old version no longer appears in test queries
