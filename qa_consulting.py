"""Consultant history, comparison and tenant-isolation regression tests."""

from __future__ import annotations

import datetime as dt
import unittest
import uuid
from pathlib import Path

import pandas as pd

from consulting.analysis import (
    available_comparisons,
    compare_snapshots,
    detect_trends,
    find_best_comparison,
    internal_benchmarks,
    moving_average,
    year_to_date_comparison,
)
from consulting.models import AnalysisSnapshot
from consulting.serialization import aggregate_result
from consulting.store import InMemoryConsultingStore


def snapshot(owner, client, month, revenue, profit, margin, *, segments=None, suffix=""):
    start = dt.date(2026, month, 1)
    end = dt.date(2026, month, 28)
    return AnalysisSnapshot(
        analysis_id=str(uuid.uuid4()), owner_user_id=owner, client_id=client,
        dataset_hash=(str(month) + suffix).ljust(64, "0")[:64],
        period_start=start, period_end=end, mapping={"umsatz": "Revenue"},
        result={"revenue": revenue, "profit": profit, "margin": margin, "segments": segments or []},
        quality_status="hoch",
    )


def dated_snapshot(owner, client, start, end, revenue, *, suffix=""):
    return AnalysisSnapshot(
        analysis_id=str(uuid.uuid4()), owner_user_id=owner, client_id=client,
        dataset_hash=(start.isoformat() + suffix).ljust(64, "0")[:64],
        period_start=start, period_end=end, mapping={"umsatz": "Revenue"},
        result={"revenue": revenue, "profit": revenue / 5, "margin": 20, "segments": []},
        quality_status="hoch",
    )


class ConsultingTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryConsultingStore()
        self.user_a = str(uuid.uuid4())
        self.user_b = str(uuid.uuid4())
        self.client_a = self.store.create_client(self.user_a, "Müller GmbH", "M-17")

    def test_01_create_client(self):
        self.assertEqual(self.client_a.name, "Müller GmbH")

    def test_02_clients_are_owner_scoped(self):
        self.assertEqual(self.store.list_clients(self.user_b), [])

    def test_03_foreign_client_id_is_denied(self):
        self.assertIsNone(self.store.get_client(self.user_b, self.client_a.client_id))

    def test_04_upload_to_client_saves_aggregates(self):
        saved = self.store.save_analysis(snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20))
        self.assertEqual(saved.result["revenue"], 100)

    def test_05_foreign_analysis_write_is_denied(self):
        with self.assertRaises(PermissionError):
            self.store.save_analysis(snapshot(self.user_b, self.client_a.client_id, 1, 100, 20, 20))

    def test_06_foreign_analysis_read_is_denied(self):
        saved = self.store.save_analysis(snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20))
        self.assertIsNone(self.store.get_analysis(self.user_b, saved.analysis_id))

    def test_07_duplicate_dataset_is_rejected(self):
        first = snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20)
        self.store.save_analysis(first)
        with self.assertRaises(ValueError):
            self.store.save_analysis(first)

    def test_08_mom_uses_percent_and_percentage_points(self):
        previous = snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20)
        current = snapshot(self.user_a, self.client_a.client_id, 2, 110, 19.8, 18)
        change = compare_snapshots(current, previous)
        self.assertAlmostEqual(change["revenue_change_pct"], 10)
        self.assertAlmostEqual(change["margin_change_pp"], -2)

    def test_09_new_and_removed_categories(self):
        previous = snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20, segments=[{"category": "A", "revenue": 100, "margin": 20}])
        current = snapshot(self.user_a, self.client_a.client_id, 2, 120, 30, 25, segments=[{"category": "B", "revenue": 120, "margin": 25}])
        change = compare_snapshots(current, previous)
        self.assertEqual(change["new_categories"], ["B"])
        self.assertEqual(change["removed_categories"], ["A"])

    def test_10_best_comparison_prefers_previous_month(self):
        january = snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20)
        february = snapshot(self.user_a, self.client_a.client_id, 2, 120, 25, 21)
        label, selected = find_best_comparison(february, [january])
        self.assertEqual((label, selected.analysis_id), ("MoM", january.analysis_id))

    def test_11_three_period_trend(self):
        history = [snapshot(self.user_a, self.client_a.client_id, month, month * 100, 20, month * 2) for month in (1, 2, 3)]
        metrics = {item["metric"] for item in detect_trends(history)}
        self.assertEqual(metrics, {"revenue", "margin"})

    def test_12_two_periods_are_not_a_trend(self):
        history = [snapshot(self.user_a, self.client_a.client_id, month, month * 100, 20, 20) for month in (1, 2)]
        self.assertEqual(detect_trends(history), [])

    def test_13_internal_segment_benchmark(self):
        current = snapshot(self.user_a, self.client_a.client_id, 2, 200, 40, 20, segments=[{"category": "Enterprise", "revenue": 120, "margin": 25}])
        benchmark = internal_benchmarks(current)[0]
        self.assertEqual(benchmark["revenue_share_pct"], 60)
        self.assertEqual(benchmark["margin_vs_company_pp"], 5)

    def test_14_serialization_contains_no_raw_rows(self):
        kpis = {
            "gesamt_umsatz": 100, "gesamt_gewinn": 20, "aktuelle_marge": 20,
            "anzahl_zeilen": 1, "anzahl_kategorien": 1, "profit_available": True,
            "financial_aggregation_available": True,
            "kategorien_daten": pd.DataFrame([{
                "Kategorie_Clean": "A", "Umsatz_Clean": 100, "Gewinn_Clean": 20,
                "Marge": 20, "Datensaetze": 1,
            }]),
            "time_analysis": {},
            "raw_df": pd.DataFrame({"email": ["secret@example.com"]}),
        }
        persisted = aggregate_result(kpis)
        self.assertNotIn("raw_df", persisted)
        self.assertNotIn("secret@example.com", str(persisted))

    def test_15_delete_client_cascades_in_memory(self):
        saved = self.store.save_analysis(snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20))
        self.assertTrue(self.store.delete_client(self.user_a, self.client_a.client_id))
        self.assertIsNone(self.store.get_analysis(self.user_a, saved.analysis_id))

    def test_16_foreign_delete_is_denied(self):
        self.assertFalse(self.store.delete_client(self.user_b, self.client_a.client_id))
        self.assertIsNotNone(self.store.get_client(self.user_a, self.client_a.client_id))

    def test_17_report_version_increments(self):
        saved = self.store.save_analysis(snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20))
        first = self.store.save_report_metadata(self.user_a, self.client_a.client_id, saved.analysis_id, {}, "a")
        second = self.store.save_report_metadata(self.user_a, self.client_a.client_id, saved.analysis_id, {}, "b")
        self.assertEqual((first.report_version, second.report_version), (1, 2))

    def test_18_foreign_report_id_is_denied(self):
        saved = self.store.save_analysis(snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20))
        report = self.store.save_report_metadata(self.user_a, self.client_a.client_id, saved.analysis_id, {}, "a")
        self.assertIsNone(self.store.get_report(self.user_b, report.report_id))

    def test_19_qoq_requires_real_quarters(self):
        q1 = dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2026, 1, 1), dt.date(2026, 3, 31), 300)
        q2 = dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2026, 4, 1), dt.date(2026, 6, 30), 360)
        comparisons = available_comparisons(q2, [q1])
        self.assertAlmostEqual(comparisons["QoQ"]["revenue_change_pct"], 20)
        april = dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2026, 4, 1), dt.date(2026, 4, 30), 120)
        january = dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2026, 1, 1), dt.date(2026, 1, 31), 100)
        self.assertNotIn("QoQ", available_comparisons(april, [january]))

    def test_20_yoy_accepts_calendar_month_length_changes(self):
        feb_2024 = dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2024, 2, 1), dt.date(2024, 2, 29), 100)
        feb_2025 = dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2025, 2, 1), dt.date(2025, 2, 28), 110)
        self.assertAlmostEqual(available_comparisons(feb_2025, [feb_2024])["YoY"]["revenue_change_pct"], 10)

    def test_21_complete_ytd(self):
        history = []
        for year, values in ((2025, (100, 200, 300)), (2026, (110, 220, 330))):
            for month, revenue in enumerate(values, start=1):
                last_day = 31 if month in {1, 3} else 28
                history.append(dated_snapshot(
                    self.user_a, self.client_a.client_id,
                    dt.date(year, month, 1), dt.date(year, month, last_day), revenue,
                    suffix=str(year),
                ))
        result = year_to_date_comparison(history, 2026, 3)
        self.assertEqual(result["revenue_current"], 660)
        self.assertAlmostEqual(result["revenue_change_pct"], 10)

    def test_22_incomplete_ytd_is_not_compared(self):
        history = [
            dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2025, 1, 1), dt.date(2025, 1, 31), 100),
            dated_snapshot(self.user_a, self.client_a.client_id, dt.date(2026, 1, 1), dt.date(2026, 1, 15), 110),
        ]
        self.assertIsNone(year_to_date_comparison(history, 2026, 1))

    def test_23_moving_average_requires_consecutive_months(self):
        history = [snapshot(self.user_a, self.client_a.client_id, month, month * 100, 20, 20) for month in (1, 2, 3)]
        self.assertEqual(moving_average(history), 200)
        gap = [history[0], history[2], snapshot(self.user_a, self.client_a.client_id, 4, 400, 20, 20)]
        self.assertIsNone(moving_average(gap))

    def test_24_report_cannot_be_attached_to_another_client(self):
        other = self.store.create_client(self.user_a, "Andere GmbH")
        saved = self.store.save_analysis(snapshot(self.user_a, self.client_a.client_id, 1, 100, 20, 20))
        with self.assertRaises(PermissionError):
            self.store.save_report_metadata(self.user_a, other.client_id, saved.analysis_id, {}, "hash")

    def test_25_empty_client_name_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.create_client(self.user_a, "   ")

    def test_26_gap_is_not_called_a_trend(self):
        history = [snapshot(self.user_a, self.client_a.client_id, month, month * 100, 20, month) for month in (1, 3, 4)]
        self.assertEqual(detect_trends(history), [])

    def test_27_migration_enforces_owner_scoped_foreign_keys(self):
        migration = Path("billing/migrations/002_consultant_workspace.sql").read_text(encoding="utf-8")
        self.assertIn("FOREIGN KEY (owner_user_id, client_id)", migration)
        self.assertIn("FOREIGN KEY (owner_user_id, client_id, analysis_id)", migration)
        self.assertNotIn("raw_file", migration.casefold())


if __name__ == "__main__":
    unittest.main(verbosity=2)
