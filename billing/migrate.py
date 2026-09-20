"""Apply ordered PostgreSQL billing migrations once."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def apply_migrations(database_url: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = migration.stem
                cursor.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                if cursor.fetchone():
                    continue
                cursor.execute(migration.read_text(encoding="utf-8"))
                cursor.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied.append(version)
    return applied


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is required")
    for applied_version in apply_migrations(url):
        print(f"Applied billing migration {applied_version}")
