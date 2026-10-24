# Schema expectations (Phases 1–3)

This document reconciles `schema_backup.sql` (dump dated 2026-10-17), migrations
`001`–`004`, and SQL used by the running application code. It is **documentation
only**. It does **not** prove the live server schema.

## Baseline tables (from schema_backup.sql)

- `users` — id, name, email UNIQUE, timestamps
- `resumes` — user_id FK → users, file_name, extracted_text, profile fields, status
- `skills` — id, name UNIQUE
- `resume_skills` — (resume_id, skill_id) PK, FKs CASCADE
- `jobs` — title, company, location, description, requirements, source, posted_at, …
- `job_skills` — (job_id, skill_id) PK, FKs CASCADE

## Columns required by current application code

| Area | Column | Introduced by | Used by |
|------|--------|---------------|---------|
| Auth | `users.password_hash` | `001_add_password_hash.sql` | `auth_service.py` |
| Ingestion / recommendations | `jobs.source_name` | `002_add_job_sync_metadata.sql` | ingestion, recommendations |
| Ingestion | `jobs.source_job_id` | `002` | ingestion upsert key |
| Ingestion | `jobs.source_url` | `002` | ingestion |
| Ingestion | `jobs.status` | `002` | ingestion, filters |
| Ingestion | `jobs.expires_at` | `002` | ingestion |
| Ingestion | `jobs.last_seen_at` | `002` | ingestion |
| Ingestion | `jobs.last_synced_at` | code/ops (see 002 family) | ingestion |
| Recommendations / ingestion | `jobs.work_mode` | `003_add_work_mode.sql` | recommendations, ingestion |
| Duplicate safety (optional DB) | UNIQUE `(source_name, source_job_id)` | `004_add_jobs_source_identity_unique.sql` | **not applied by default** |

## Application-level duplicate handling

- `job_ingestion_service._sync_job` SELECTs by `(source_name, source_job_id)`, then UPDATE or INSERT.
- `_source_id` and `_sync_job` reject missing/blank provider IDs and blank source names.
- Recommendation path deduplicates listings in memory (see `recommendation_service`).
- Database UNIQUE (`004`) is the concurrent-ingestion safety net; **treat as inactive until applied on a verified target**.

## Live verification checklist (staging only)

On a single verified connection to `127.0.0.1:33309` / `resume_analyzer_restore_test`:

1. `SELECT DATABASE(), @@port, @@server_uuid;`
2. `SHOW COLUMNS FROM users LIKE 'password_hash';`
3. `SHOW COLUMNS FROM jobs WHERE Field IN ('source_name','source_job_id','work_mode','status','expires_at','last_seen_at','source_url','last_synced_at');`
4. `SHOW INDEX FROM jobs WHERE Key_name = 'uq_jobs_source_identity';`
5. Do **not** run writes unless isolation is re-confirmed and authorized.

## Historical row-count claims

Resume ID 15 / 15 skills, 5 sample jobs, and 24 skill mappings remain **unverified**
historical claims. Do not recreate them to satisfy documentation.


## 2026-10-19 file-only index reconciliation

The baseline `schema_backup.sql` jobs definition has neither source-identity
columns nor a source-identity index. Migration 002 adds those columns and
UNIQUE `uq_jobs_source_id(source_name, source_job_id)`. Migration 004 adds
UNIQUE `uq_jobs_source_identity(source_name, source_job_id)`: the same ordered
columns with a different name. Applying both would create redundant unique
indexes; absence of the 004 index name does not prove absence of uniqueness.
Historical Phase 5 reports claim `uq_jobs_source_id` existed, but do not establish
current staging identity or schema. Current application SQL uses the columns,
not either index name.

No migration was edited or applied. Live index existence and migration history
remain UNKNOWN. Before deciding whether 004 is needed, the owner must establish
staging credentials and independently trusted database/port/UUID/data-directory
markers; a later authorized read-only check must verify all markers on the same
authenticated connection and inspect full index definitions (ordered columns,
uniqueness, prefix lengths), not only the index name. Do not apply 004 blindly.
The earlier table/checklist is historical guidance, not live verification.
