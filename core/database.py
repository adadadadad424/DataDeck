"""Bounded PostgreSQL connections shared by billing and consultant storage."""

from __future__ import annotations

import os
import threading

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row


_POOL_LOCK = threading.RLock()
_POOLS: dict[str, ConnectionPool] = {}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _connection_kwargs(*, migration: bool = False) -> dict:
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
    return {
        "row_factory": dict_row,
        "connect_timeout": connect_timeout,
        "options": options,
        "application_name": "datadeck",
    }


def _pool_for(database_url: str) -> ConnectionPool:
    with _POOL_LOCK:
        pool = _POOLS.get(database_url)
        if pool is None:
            min_size = _bounded_int("DB_POOL_MIN_SIZE", 0, 0, 5)
            max_size = _bounded_int("DB_POOL_MAX_SIZE", 4, 1, 20)
            max_size = max(min_size or 1, max_size)
            pool = ConnectionPool(
                conninfo=database_url,
                min_size=min_size,
                max_size=max_size,
                timeout=_bounded_int("DB_POOL_TIMEOUT_SECONDS", 5, 1, 30),
                max_lifetime=_bounded_int("DB_POOL_MAX_LIFETIME_SECONDS", 1_800, 60, 7_200),
                max_idle=_bounded_int("DB_POOL_MAX_IDLE_SECONDS", 300, 30, 1_800),
                reconnect_timeout=_bounded_int("DB_POOL_RECONNECT_SECONDS", 10, 1, 60),
                kwargs=_connection_kwargs(),
                open=False,
                name="datadeck-app",
            )
            pool.open(wait=False)
            _POOLS[database_url] = pool
        return pool


def connect_postgres(database_url: str, *, migration: bool = False):
    if migration:
        return psycopg.connect(database_url, **_connection_kwargs(migration=True))
    return _pool_for(database_url).connection()


def close_postgres_pools() -> None:
    with _POOL_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


def postgres_pool_stats(database_url: str) -> dict[str, int]:
    stats = _pool_for(database_url).get_stats()
    allowed = {
        "pool_size", "pool_available", "requests_waiting", "requests_num",
        "requests_errors", "connections_num", "connections_errors",
    }
    return {key: int(value) for key, value in stats.items() if key in allowed}
