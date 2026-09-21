# PostgreSQL Backup and Restore

## Policy

The Render Free database is suitable for closed-beta validation, not a contractual
recovery objective. It expires unless upgraded and does not provide the managed backup
retention expected for production. Before accepting real customer history, move to a
plan with managed backups and define an approved retention period.

Until then, an operator can create a logical `pg_dump --format=custom` backup. The dump
must be encrypted immediately with AES-256 (or stored in an equivalently encrypted
backup service), kept outside the repository and deleted when its retention expires.
Connection strings and encryption keys must only come from the secret store.

## Restore drill

1. Create an isolated empty database, never the live database.
2. Decrypt the selected dump only into protected temporary storage.
3. Run `pg_restore --no-owner --no-acl --exit-on-error` against the isolated target.
4. Run the read-only migration verification and persistence QA.
5. Record duration, migration count and result without credentials or customer data.
6. Remove the restored database, decrypted dump and one-time encryption key.

The 2026-09-21 closed-beta drill restored the live schema into an isolated temporary
database on the same free Render PostgreSQL instance. Verification passed with five
migrations, three foreign keys and 25 indexes; the temporary database and local dump
files were removed afterward.

## Recovery objectives

- Closed beta target RPO: 24 hours after automated encrypted backups are configured.
- Closed beta target RTO: 4 hours, verified by a quarterly restore drill.
- Current Free-plan status: targets are not guaranteed; this is a launch blocker for
  paying customers, not for synthetic closed-beta validation.
