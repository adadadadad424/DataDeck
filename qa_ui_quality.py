"""Fokussierte Regressionstests fuer darstellende UI-Logik."""

import datetime
import unittest

from core.formatting import format_compact_number, format_de_date, format_de_number
from main import _mapping_requires_review, _stable_mapping_key


class UIQualityTests(unittest.TestCase):
    def test_german_number_format(self):
        self.assertEqual(format_de_number(14545245.38), "14.545.245,38")

    def test_compact_million_format(self):
        self.assertEqual(format_compact_number(14545245.38), "14,55 Mio.")

    def test_compact_value_keeps_thousands_readable(self):
        self.assertEqual(format_compact_number(845420), "845.420")

    def test_compact_negative_value(self):
        self.assertEqual(format_compact_number(-1250000), "-1,25 Mio.")

    def test_compact_small_currency_omits_cents(self):
        self.assertEqual(format_compact_number(-100), "-100")

    def test_invalid_number_is_not_rendered_as_nan(self):
        self.assertEqual(format_de_number(float("nan")), "—")

    def test_date_format(self):
        self.assertEqual(format_de_date(datetime.date(2026, 1, 12)), "12.01.2026")

    def test_low_mapping_confidence_requires_review(self):
        warnings = {"mapping_confidence": {"umsatz": "mittel", "gewinn": "hoch"}}
        self.assertTrue(_mapping_requires_review(warnings))

    def test_high_mapping_confidence_stays_quiet(self):
        warnings = {
            "mapping_confidence": {
                "umsatz": "hoch", "gewinn": "hoch", "kosten": "nicht_verfuegbar", "kategorie": "hoch"
            }
        }
        self.assertFalse(_mapping_requires_review(warnings))

    def test_missing_profit_and_cost_requires_review(self):
        warnings = {
            "mapping_confidence": {
                "umsatz": "hoch", "gewinn": "nicht_verfuegbar",
                "kosten": "nicht_verfuegbar", "kategorie": "hoch",
            }
        }
        self.assertTrue(_mapping_requires_review(warnings))

    def test_mapping_cache_key_is_order_independent(self):
        first = {"umsatz": "Revenue", "gewinn": "Profit"}
        second = {"gewinn": "Profit", "umsatz": "Revenue"}
        self.assertEqual(_stable_mapping_key(first), _stable_mapping_key(second))


if __name__ == "__main__":
    unittest.main(verbosity=2)
