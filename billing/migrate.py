"""Transactional, checksummed PostgreSQL migrations for DataDeck."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from psycopg import sql

from core.database import connect_postgres


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATION_NAME = re.compile(r"^\d{3}(?:_[a-z0-9_]+)?$")
EXPECTED_TABLES = {
    "schema_migrations", "billing_users", "stripe_events", "workspace_users",
    "consulting_clients", "analysis_snapshots", "report_versions",
}


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    checksum: str
    sql_text: str


def load_migrations() -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if not MIGRATION_NAME.fullmatch(path.stem):
            raise MigrationError(f"Ungültiger Migrationsname: {path.name}")
        content = path.read_bytes()
        migrations.append(Migration(
            version=path.stem,
            checksum=hashlib.sha256(content).hexdigest(),
            sql_text=content.decode("utf-8"),
        ))
    if not migrations or len({item.version for item in migrations}) != len(migrations):
        raise MigrationError("Migrationen fehlen oder sind nicht eindeutig")
    return migrations


def _set_schema(cursor, schema: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise MigrationError("Ungültiges Datenbankschema")
    cursor.execute(sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(sql.Identifier(schema)))


def _bootstrap_journal(cursor) -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version TEXT PRIMARY KEY,
               checksum TEXT,
               applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
           )"""
    )
    cursor.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT")
    cursor.execute("SELECT version FROM schema_migrations WHERE checksum IS NULL LIMIT 1")
    if cursor.fetchone():
        raise MigrationError(
            "Migration journal contains a legacy row without checksum; explicit operator review required"
        )


def _apply_with_cursor(cursor, migrations: list[Migration]) -> list[str]:
    _bootstrap_journal(cursor)
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (7_431_920_261,))
    cursor.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
    recorded = {row["version"]: row["checksum"] for row in cursor.fetchall()}
    unknown = sorted(set(recorded) - {item.version for item in migrations})
    if unknown:
        raise MigrationError("Unbekannte Migrationen im Journal: " + ", ".join(unknown))

    applied: list[str] = []
    for migration in migrations:
        previous_checksum = recorded.get(migration.version)
        if previous_checksum:
            if previous_checksum != migration.checksum:
                raise MigrationError(
                    f"Checksum mismatch for migration {migration.version}; deployment stopped"
                )
            continue
        cursor.execute(migration.sql_text)
        cursor.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
            (migration.version, migration.checksum),
        )
        applied.append(migration.version)
    cursor.execute("ALTER TABLE schema_migrations ALTER COLUMN checksum SET NOT NULL")
    return applied


def audit_schema(cursor) -> dict[str, int | list[str]]:
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
    )
    tables = {row["table_name"] for row in cursor.fetchall()}
    missing = sorted(EXPECTED_TABLES - tables)
    if missing:
        raise MigrationError("Schema audit missing tables: " + ", ".join(missing))
    cursor.execute(
        "SELECT COUNT(*) AS count FROM information_schema.table_constraints "
        "WHERE table_schema = current_schema() AND constraint_type = 'FOREIGN KEY'"
    )
    foreign_keys = int(cursor.fetchone()["count"])
    cursor.execute("SELECT COUNT(*) AS count FROM pg_indexes WHERE schemaname = current_schema()")
    indexes = int(cursor.fetchone()["count"])
    cursor.execute("SELECT COUNT(*) AS count FROM schema_migrations")
    migration_count = int(cursor.fetchone()["count"])
    if foreign_keys < 3 or indexes < 10:
        raise MigrationError("Schema audit found insufficient constraints or indexes")
    return {
        "tables": sorted(tables),
        "foreign_keys": foreign_keys,
        "indexes": indexes,
        "migrations": migration_count,
    }


def dry_run_migrations(database_url: str) -> dict[str, int | list[str]]:
    schema = f"migration_check_{uuid.uuid4().hex[:12]}"
    with connect_postgres(database_url, migration=True) as connection:
        with connection.transaction(force_rollback=True):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                _set_schema(cursor, schema)
                _apply_with_cursor(cursor, load_migrations())
                return audit_schema(cursor)


def apply_migrations(database_url: str, *, schema: str = "public") -> list[str]:
    migrations = load_migrations()
    with connect_postgres(database_url, migration=True) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _set_schema(cursor, schema)
                applied = _apply_with_cursor(cursor, migrations)
                audit_schema(cursor)
        return applied


def verify_migrations(database_url: str, *, schema: str = "public") -> dict[str, int | list[str]]:
    """Verify connectivity, journal checksums and schema shape without changing data."""
    migrations = load_migrations()
    with connect_postgres(database_url, migration=True) as connection:
        with connection.transaction(force_rollback=True), connection.cursor() as cursor:
            _set_schema(cursor, schema)
            cursor.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            )
            recorded = {row["version"]: row["checksum"] for row in cursor.fetchall()}
            expected = {item.version: item.checksum for item in migrations}
            if recorded != expected:
                missing = sorted(set(expected) - set(recorded))
                unknown = sorted(set(recorded) - set(expected))
                mismatched = sorted(
                    version for version in set(expected) & set(recorded)
                    if expected[version] != recorded[version]
                )
                details = []
                if missing:
                    details.append("missing=" + ",".join(missing))
                if unknown:
                    details.append("unknown=" + ",".join(unknown))
                if mismatched:
                    details.append("checksum=" + ",".join(mismatched))
                raise MigrationError("Migration verification failed: " + "; ".join(details))
            return audit_schema(cursor)


def main() -> int:
    parser = argparse.ArgumentParser(description="DataDeck PostgreSQL migrations")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    if args.dry_run:
        result = dry_run_migrations(database_url)
        print(
            "Migration dry-run PASS: "
            f"{result['migrations']} migrations, {result['foreign_keys']} foreign keys, "
            f"{result['indexes']} indexes"
        )
        return 0
    applied = apply_migrations(database_url)
    print(f"Migration PASS: {len(applied)} newly applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
