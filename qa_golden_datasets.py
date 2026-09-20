"""Known-answer financial datasets for release regression testing."""

from __future__ import annotations

import unittest

import pandas as pd

from core.analysis import calculate_kpis
from core.data_processing import (
    assess_data_quality,
    clean_and_prepare_data,
    normalize_dataframe_structure,
)


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


class GoldenMatrixTests(unittest.TestCase):
    """Known-answer cases representing real import variation, not snapshots."""


def _currency_case(value, expected):
    def test(self):
        result = analyze(pd.DataFrame({"Kategorie": ["A"], "Umsatz": [value], "Gewinn": [0]}))
        self.assertAlmostEqual(result["gesamt_umsatz"], expected, places=6)
    return test


def _missing_category_case(value):
    def test(self):
        clean, _ = clean_and_prepare_data(
            pd.DataFrame({"Kategorie": [value, "A"], "Umsatz": [100, 50], "Gewinn": [10, 5]})
        )
        self.assertEqual(clean["Kategorie_Clean"].iloc[0], "Unbekannt")
    return test


def _date_case(value, expected):
    def test(self):
        clean, _ = clean_and_prepare_data(pd.DataFrame({
            "Datum": [value], "Kategorie": ["A"], "Umsatz": [100], "Gewinn": [10],
        }))
        self.assertEqual(clean["Datum_Clean"].iloc[0].date().isoformat(), expected)
    return test


def _financial_case(revenue, costs, expected_profit, expected_margin):
    def test(self):
        result = analyze(pd.DataFrame({
            "Segment": ["A"], "Revenue": [revenue], "Costs": [costs],
        }))
        self.assertAlmostEqual(result["gesamt_gewinn"], expected_profit, places=6)
        if expected_margin is None:
            self.assertTrue(pd.isna(result["aktuelle_marge"]))
        else:
            self.assertAlmostEqual(result["aktuelle_marge"], expected_margin, places=6)
    return test


def _category_case(values, expected):
    def test(self):
        clean, _ = clean_and_prepare_data(
            pd.DataFrame({"Kategorie": values, "Umsatz": [100] * len(values), "Gewinn": [10] * len(values)}),
            {"normalize_categories": True},
        )
        self.assertEqual(clean["Kategorie_Clean"].tolist(), expected)
        self.assertEqual(clean["Kategorie_Original"].tolist(), [str(value).strip() for value in values])
    return test


CURRENCY_CASES = [
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("€ 1.234,56", 1234.56),
    ("1.234,56 €", 1234.56), ("$1,234.56", 1234.56), ("1 234,56", 1234.56),
    ("-1.250", -1250), ("(1.250)", -1250), ("-1.250,50", -1250.5),
    ("1.250,50-", -1250.5), ("CHF 9'500.25", 9500.25), (0, 0),
]
for index, (value, expected) in enumerate(CURRENCY_CASES, start=1):
    setattr(GoldenMatrixTests, f"test_01_currency_{index:02d}", _currency_case(value, expected))

for index, token in enumerate(["NULL", "null", "N/A", "n/a", "NA", "-", "—", "k.A."], start=1):
    setattr(GoldenMatrixTests, f"test_02_missing_{index:02d}", _missing_category_case(token))

DATE_CASES = [
    ("31.01.2026", "2026-01-31"), ("2026-01-31", "2026-01-31"),
    ("31/01/2026", "2026-01-31"), ("31.01.26", "2026-01-31"),
    ("31 January 2026", "2026-01-31"), ("31 Januar 2026", "2026-01-31"),
    (46053, "2026-01-31"), ("15 März 2025", "2025-03-15"),
]
for index, (value, expected) in enumerate(DATE_CASES, start=1):
    setattr(GoldenMatrixTests, f"test_03_date_{index:02d}", _date_case(value, expected))

FINANCIAL_CASES = [
    (100, 40, 60, 60), (0, 0, 0, None), (100, 0, 100, 100),
    (100, 120, -20, -20), (-100, 0, -100, 100), (-100, -20, -80, 80),
    (100, -20, 120, 120), ("1.000,00", "250,00", 750, 75),
    (0.01, 0.02, -0.01, -100), (1_000_000_000, 999_999_999, 1, 0.0000001),
]
for index, values in enumerate(FINANCIAL_CASES, start=1):
    setattr(GoldenMatrixTests, f"test_04_financial_{index:02d}", _financial_case(*values))

CATEGORY_CASES = [
    (["Enterprise", "enterprise"], ["Enterprise", "Enterprise"]),
    (["Pro ", " PRO"], ["Pro", "Pro"]),
    (["SMB", "smb", "Smb"], ["SMB", "SMB", "SMB"]),
    (["Nord", "Süd"], ["Nord", "Süd"]),
]
for index, values in enumerate(CATEGORY_CASES, start=1):
    setattr(GoldenMatrixTests, f"test_05_category_{index:02d}", _category_case(*values))


def _structure_case(kind):
    def test(self):
        if kind == "empty_column":
            frame = pd.DataFrame({"Umsatz": [100], "Gewinn": [10], "Unnamed: 0": [None]})
            normalized = normalize_dataframe_structure(frame)
            self.assertNotIn("Unnamed: 0", normalized.columns)
        elif kind == "duplicate_column":
            frame = pd.DataFrame([[100, 50, 10]], columns=["Umsatz", "Umsatz", "Gewinn"])
            normalized = normalize_dataframe_structure(frame)
            self.assertEqual(list(normalized.columns), ["Umsatz", "Umsatz__2", "Gewinn"])
        elif kind == "blank_column":
            frame = pd.DataFrame([[100, 10]], columns=["Umsatz", ""])
            normalized = normalize_dataframe_structure(frame)
            self.assertEqual(list(normalized.columns), ["Umsatz", "Spalte_2"])
        elif kind == "refund":
            result = analyze(pd.DataFrame({"Kategorie": ["Sale", "Refund"], "Umsatz": [200, -50], "Gewinn": [60, -50]}))
            self.assertEqual(result["gesamt_umsatz"], 150)
        else:
            result = analyze(pd.DataFrame({"Kategorie": ["A"], "Umsatz": [float("inf")], "Gewinn": [10]}))
            self.assertEqual(result["anzahl_zeilen"], 0)
    return test


for index, kind in enumerate(["empty_column", "duplicate_column", "blank_column", "refund"], start=1):
    setattr(GoldenMatrixTests, f"test_06_structure_{index:02d}", _structure_case(kind))


if __name__ == "__main__":
    unittest.main(verbosity=2)
