# DataDeck Persistence

## Stored data

PostgreSQL stores only account/billing state and the consultant workspace:

- owner-scoped client name and optional internal reference
- immutable aggregate analysis snapshots
- edited executive summary and consultant comment
- report settings, content hash and monotonically increasing report version
- analysis engine/schema version and migration journal checksums

Uploaded files, raw rows, generated PDF bytes, OAuth tokens and Gemini prompts are
never persisted. Deleting a client cascades to its aggregate analyses and report
metadata. Every read and write includes the server-derived owner ID.

## Migrations

Migration files in `billing/migrations` are append-only. `python -m billing.migrate
--dry-run` applies every migration inside a temporary schema and rolls the transaction
back. The normal command takes a transaction advisory lock, verifies SHA-256 checksums,
applies pending files transactionally and audits tables, foreign keys and indexes.

Never edit an applied migration. Add the next numbered file. Production startup is
read-only: it refuses to start if the database is unavailable, a migration is missing,
an unknown migration exists or a checksum changed.

## Connection policy

The app uses a bounded process-local pool. Production defaults are a maximum of four
connections, five-second checkout/connect timeout, five-second statement timeout and
ten-second idle-transaction timeout. A transient database failure raises a controlled
workspace error; it does not fall back to a shared in-memory history.

## Validation

`qa_persistence.py` is destructive only to its own synthetic owner IDs and runs against
an explicitly supplied `DATADECK_INTEGRATION_DATABASE_URL`. It validates three
consultant workflows, 18 periods, owner isolation, retry idempotency, immutable history,
report versions, pool restart persistence, concurrent reads and a rolled-back scale
probe with 100 users, 2,000 clients and 48,000 analyses.
