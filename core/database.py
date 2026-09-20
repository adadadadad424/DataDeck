"""Bounded PostgreSQL connections shared by billing and consultant storage."""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def connect_postgres(database_url: str, *, migration: bool = False):
    connect_timeout = _bounded_int("DB_CONNECT_TIMEOUT_SECONDS", 5, 1, 30)
    statement_timeout = _bounded_int(
        "DB_MIGRATION_TIMEOUT_MS" if migration else "DB_STATEMENT_TIMEOUT_MS",
        30_000 if migration else 5_000,
        500,
        120_000,
    )
    options = (
        f"-c statement_timeout={statement_timeout} "
        "-c lock_timeout=3000 -c idle_in_transaction_session_timeout=10000"
    )
    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=connect_timeout,
        options=options,
        application_name="datadeck",
    )
