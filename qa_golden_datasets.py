"""Known-answer financial datasets for release regression testing."""

from __future__ import annotations

import unittest

import pandas as pd

from core.analysis import calculate_kpis
from core.data_processing import assess_data_quality, clean_and_prepare_data


def analyze(raw: pd.DataFrame) -> dict:
    clean, warnings = clean_and_prepare_data(raw)
    quality = assess_data_quality(raw, clean, warnings)
    return calculate_kpis(clean, {**warnings, "data_quality": quality})


class GoldenDatasetTests(unittest.TestCase):
    def test_measured_profit_dataset(self):
        result = analyze(pd.DataFrame({
            "Kategorie": ["A", "B"], "Umsatz": [100, 200], "Gewinn": [20, 50]
        }))
        self.assertEqual(result["gesamt_umsatz"], 300)
        self.assertEqual(result["gesamt_gewinn"], 70)
        self.assertAlmostEqual(result["aktuelle_marge"], 23.333333, places=5)
        self.assertEqual(result["top_performer"][0]["Kategorie_Clean"], "B")

    def test_profit_calculated_from_costs(self):
        result = analyze(pd.DataFrame({
            "Produkt": ["Paket"], "Revenue": [1000], "Cost of Goods Sold": [400]
        }))
        self.assertEqual(result["gesamt_gewinn"], 600)
        self.assertEqual(result["aktuelle_marge"], 60)
        self.assertEqual(result["metrics"]["gewinn"]["status"], "ESTIMATED")

    def test_revenue_only_has_no_invented_profit(self):
        result = analyze(pd.DataFrame({"Plan": ["Pro", "Starter"], "MRR": [500, 100]}))
        self.assertEqual(result["gesamt_umsatz"], 600)
        self.assertFalse(result["profit_available"])
        self.assertTrue(pd.isna(result["gesamt_gewinn"]))
        self.assertEqual(result["metrics"]["marge"]["status"], "UNAVAILABLE")

    def test_complete_month_comparison(self):
        result = analyze(pd.DataFrame({
            "Kategorie": ["A", "A", "A", "A"],
            "Datum": ["2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"],
            "Umsatz": [100, 200, 150, 250],
            "Gewinn": [30, 60, 45, 75],
        }))
        comparison = result["time_analysis"]
        self.assertTrue(comparison["comparison_available"])
        self.assertEqual(comparison["comparison_type"], "FULL_MONTH")
        self.assertAlmostEqual(comparison["revenue_change_pct"], 33.333333, places=5)

    def test_mixed_currency_is_not_aggregated(self):
        result = analyze(pd.DataFrame({
            "Kategorie": ["EU", "US"],
            "Umsatz": ["EUR 100", "USD 200"],
            "Gewinn": ["EUR 20", "USD 50"],
        }))
        self.assertFalse(result["financial_aggregation_available"])
        self.assertEqual(result["top_performer"], [])
        self.assertEqual(result["metrics"]["umsatz"]["status"], "LIMITED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
