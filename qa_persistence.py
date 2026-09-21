"""Real PostgreSQL validation for migration, isolation and consultant history."""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pandas as pd

from consulting.analysis import detect_trends
from consulting.models import AnalysisSnapshot
from consulting.serialization import aggregate_result
from consulting.store import PostgresConsultingStore
from billing.migrate import verify_migrations
from core.analysis import calculate_kpis
from core.data_processing import assess_data_quality, clean_and_prepare_data, load_and_validate_file
from core.database import close_postgres_pools, connect_postgres, postgres_pool_stats


FIXTURE = Path(__file__).with_name("fixtures") / "consultant_validation.json"
OWNER_NAMESPACE = uuid.UUID("4cae11f7-8f55-4a68-8608-07ef45e270ba")


def _assert_close(actual, expected, label: str) -> None:
    if abs(float(actual) - float(expected)) > 0.0001:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _snapshot_from_period(owner_id: str, client_id: str, case_name: str, period: dict) -> AnalysisSnapshot:
    year, month = map(int, period["month"].split("-"))
    period_end = int(period.get("partial_end", calendar.monthrange(year, month)[1]))
    rows = [
        {
            "Datum": f"{year:04d}-{month:02d}-{period_end:02d}",
            "Kategorie": category,
            "Umsatz": revenue,
            "Gewinn": profit,
        }
        for category, revenue, profit in period["segments"]
    ]
    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
    loaded, truncated, _ = load_and_validate_file(csv_bytes, "validation.csv", True)
    if truncated:
        raise AssertionError("Small validation fixture was unexpectedly truncated")
    clean, warnings = clean_and_prepare_data(loaded)
    quality = assess_data_quality(loaded, clean, warnings)
    kpis = calculate_kpis(clean, {**warnings, "data_quality": quality})
    expected_revenue, expected_profit, expected_margin = period["expected"]
    _assert_close(kpis["gesamt_umsatz"], expected_revenue, f"{case_name} revenue")
    _assert_close(kpis["gesamt_gewinn"], expected_profit, f"{case_name} profit")
    _assert_close(kpis["aktuelle_marge"], expected_margin, f"{case_name} margin")
    period_start = dt.date(year, month, 1)
    return AnalysisSnapshot(
        analysis_id=str(uuid.uuid4()),
        owner_user_id=owner_id,
        client_id=client_id,
        dataset_hash=hashlib.sha256(csv_bytes).hexdigest(),
        period_start=period_start,
        period_end=dt.date(year, month, period_end),
        mapping={"revenue": "Umsatz", "profit": "Gewinn", "category": "Kategorie"},
        result=aggregate_result(kpis),
        quality_status="GOOD",
        insights=[{"type": "validation", "text": "Synthetic expected result confirmed."}],
        executive_summary=f"Validated synthetic case {case_name}.",
        consultant_comment="Final validation comment.",
        analysis_version="0.9.1-beta",
        analysis_engine_version="0.9.1-beta",
        analysis_schema_version=1,
    )


def _cleanup(database_url: str, owner_ids: list[str]) -> None:
    close_postgres_pools()
    with connect_postgres(database_url, migration=True) as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM workspace_users WHERE user_id = ANY(%s::uuid[])", (owner_ids,))


def _run_scale_probe(database_url: str) -> None:
    """Validate the target access path with 100 users and 48,000 analyses, then roll it back."""
    owner_id = str(uuid.UUID(hashlib.md5(b"scale-owner-1").hexdigest()))
    client_id = str(uuid.UUID(hashlib.md5(b"scale-client-1-1").hexdigest()))
    with connect_postgres(database_url, migration=True) as connection:
        with connection.transaction(force_rollback=True), connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO workspace_users (user_id)
                   SELECT md5('scale-owner-' || owner_no::text)::uuid
                   FROM generate_series(1, 100) AS owner_no"""
            )
            cursor.execute(
                """INSERT INTO consulting_clients (client_id, owner_user_id, name)
                   SELECT md5('scale-client-' || owner_no::text || '-' || client_no::text)::uuid,
                          md5('scale-owner-' || owner_no::text)::uuid,
                          'Scale Client ' || client_no::text
                   FROM generate_series(1, 100) AS owner_no
                   CROSS JOIN generate_series(1, 20) AS client_no"""
            )
            cursor.execute(
                """INSERT INTO analysis_snapshots (
                       analysis_id, owner_user_id, client_id, dataset_hash,
                       period_start, period_end, mapping, analysis_result, quality_status,
                       analysis_version, analysis_engine_version, analysis_schema_version
                   )
                   SELECT md5('scale-analysis-' || owner_no::text || '-' || client_no::text || '-' || period_no::text)::uuid,
                          md5('scale-owner-' || owner_no::text)::uuid,
                          md5('scale-client-' || owner_no::text || '-' || client_no::text)::uuid,
                          md5('scale-dataset-' || owner_no::text || '-' || client_no::text || '-' || period_no::text)
                              || md5('scale-dataset-b-' || owner_no::text || '-' || client_no::text || '-' || period_no::text),
                          make_date(2024 + ((period_no - 1) / 12)::int, ((period_no - 1) % 12) + 1, 1),
                          (make_date(2024 + ((period_no - 1) / 12)::int, ((period_no - 1) % 12) + 1, 1)
                              + INTERVAL '1 month - 1 day')::date,
                          '{}'::jsonb,
                          jsonb_build_object('revenue', period_no * 1000, 'profit', period_no * 200, 'margin', 20),
                          'GOOD', 'scale', 'scale', 1
                   FROM generate_series(1, 100) AS owner_no
                   CROSS JOIN generate_series(1, 20) AS client_no
                   CROSS JOIN generate_series(1, 24) AS period_no"""
            )
            started = time.perf_counter()
            cursor.execute(
                """SELECT analysis_id FROM analysis_snapshots
                   WHERE owner_user_id = %s AND client_id = %s
                   ORDER BY period_end DESC LIMIT 24""",
                (owner_id, client_id),
            )
            rows = cursor.fetchall()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if len(rows) != 24 or elapsed_ms > 1_000:
                raise AssertionError(f"Scale history query failed reliability target ({elapsed_ms:.1f} ms)")


def run(database_url: str) -> None:
    verified = verify_migrations(database_url)
    if verified["migrations"] < 5:
        raise AssertionError("Production schema is missing persistence migrations")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    owner_ids = [str(uuid.uuid5(OWNER_NAMESPACE, case["name"])) for case in fixture["cases"]]
    store = PostgresConsultingStore(database_url)
    try:
        _cleanup(database_url, owner_ids)
        store = PostgresConsultingStore(database_url)
        saved_by_owner: dict[str, tuple[str, list[AnalysisSnapshot]]] = {}

        for owner_id, case in zip(owner_ids, fixture["cases"]):
            client = store.create_client(owner_id, case["name"], "SYNTHETIC-VALIDATION")
            duplicate_client = store.create_client(owner_id, case["name"], "SYNTHETIC-VALIDATION")
            if duplicate_client.client_id != client.client_id:
                raise AssertionError("Client double-submit created a duplicate")
            snapshots = []
            for period in case["periods"]:
                snapshot = _snapshot_from_period(owner_id, client.client_id, case["name"], period)
                snapshots.append(store.save_analysis(snapshot))
            trends = sorted(item["metric"] for item in detect_trends(snapshots))
            if trends != sorted(case["expected_trends"]):
                raise AssertionError(f"{case['name']} trends: expected {case['expected_trends']}, got {trends}")
            first_report = store.save_report_metadata(
                owner_id, client.client_id, snapshots[-1].analysis_id,
                {"locale": "de-DE", "validated": True}, hashlib.sha256(case["name"].encode()).hexdigest(),
            )
            second_report = store.save_report_metadata(
                owner_id, client.client_id, snapshots[-1].analysis_id,
                {"locale": "de-DE", "validated": True, "revision": 2}, hashlib.sha256((case["name"] + "2").encode()).hexdigest(),
            )
            if (first_report.report_version, second_report.report_version) != (1, 2):
                raise AssertionError("Report version sequence is not monotonic")
            saved_by_owner[owner_id] = (client.client_id, snapshots)

        first_owner = owner_ids[0]
        first_client, first_snapshots = saved_by_owner[first_owner]
        retried = store.save_analysis(first_snapshots[0])
        if retried.analysis_id != first_snapshots[0].analysis_id:
            raise AssertionError("Identical analysis retry was not idempotent")
        try:
            store.save_analysis(replace(first_snapshots[0], analysis_id=str(uuid.uuid4())))
        except ValueError as exc:
            if "bereits gespeichert" not in str(exc):
                raise
        else:
            raise AssertionError("Duplicate analysis was accepted")

        foreign_owner = owner_ids[1]
        if store.get_client(foreign_owner, first_client) is not None:
            raise AssertionError("Cross-owner client access leaked")
        if store.get_analysis(foreign_owner, first_snapshots[0].analysis_id) is not None:
            raise AssertionError("Cross-owner analysis access leaked")

        with ThreadPoolExecutor(max_workers=10) as executor:
            counts = list(executor.map(
                lambda owner: len(store.list_clients(owner)),
                [owner_ids[index % len(owner_ids)] for index in range(30)],
            ))
        if counts != [1] * 30:
            raise AssertionError("Concurrent owner-scoped reads were inconsistent")

        close_postgres_pools()
        restarted_store = PostgresConsultingStore(database_url)
        restored = restarted_store.list_analyses(first_owner, first_client)
        if len(restored) != 6 or restored[0].analysis_engine_version != "0.9.1-beta":
            raise AssertionError("History did not survive connection-pool restart")
        if restored[0].consultant_comment != "Final validation comment.":
            raise AssertionError("Edited consultant text was not persisted")

        with connect_postgres(database_url, migration=True) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'analysis_snapshots'"
            )
            columns = {row["column_name"] for row in cursor.fetchall()}
            if columns & {"raw_file", "raw_data", "source_rows", "upload_content"}:
                raise AssertionError("Raw upload storage column exists")

        try:
            with connect_postgres(database_url, migration=True) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE analysis_snapshots SET quality_status = 'CHANGED' WHERE analysis_id = %s",
                    (first_snapshots[0].analysis_id,),
                )
        except Exception as exc:
            if "immutable" not in str(exc).casefold():
                raise
        else:
            raise AssertionError("Historical snapshot update was accepted")

        stats = postgres_pool_stats(database_url)
        if stats.get("pool_size", 0) > int(os.getenv("DB_POOL_MAX_SIZE", "4")):
            raise AssertionError("Connection pool exceeded configured maximum")
        _run_scale_probe(database_url)
    finally:
        _cleanup(database_url, owner_ids)


def main() -> int:
    database_url = os.getenv("DATADECK_INTEGRATION_DATABASE_URL", "").strip()
    if not database_url:
        print("PostgreSQL persistence QA: SKIP (DATADECK_INTEGRATION_DATABASE_URL not configured)")
        return 0
    run(database_url)
    print(
        "PostgreSQL persistence QA: PASS "
        "(3 workflows, 18 periods, restart, isolation, immutability, 48k-row scale probe)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
