# Persistence and Reliability Validation

Date: 2026-09-21

## Environment

- Render web service and PostgreSQL 17 in Frankfurt
- both resources on explicitly selected free plans
- internal Render database URL linked as `DATABASE_URL`
- five transactional, checksummed migrations applied

## Results

| Check | Result |
|---|---|
| Migration dry-run and rollback | PASS |
| Migration replay/idempotency | PASS |
| Schema/checksum startup verification | PASS |
| 3 consultant workflows / 18 periods | PASS |
| Expected KPI and trend outcomes | PASS |
| Owner isolation and concurrent reads | PASS |
| Duplicate request handling | PASS |
| Immutable snapshots and report versions | PASS |
| Persistence after pool restart | PASS |
| 100 users / 2,000 clients / 48,000 analyses | PASS |
| Encrypted dump and isolated restore | PASS |
| Raw upload persistence scan | PASS |

## Known limits

- Render Free can sleep, has constrained CPU/RAM and its free PostgreSQL expires.
- Managed backup retention and guaranteed RPO/RTO require a paid production database;
  no upgrade was performed in this sprint.
- A true second-device/two-Google-account browser test requires a second approved human
  beta account. Database-level multi-user isolation is automated and passed.
- Long-running Gemini availability depends on the external provider and configured
  quota. Deterministic KPI calculation remains local and does not depend on Gemini.

## Recommendation

The persistence implementation is suitable for a synthetic closed beta. Before real
customer or paid use, upgrade the database, enable managed backups and alerts, complete
a second-account browser isolation test, and repeat the restore drill on the selected
production plan.
