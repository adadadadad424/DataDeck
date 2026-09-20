"""Fokussierte Regressionstests fuer darstellende UI-Logik."""

import datetime
import base64
import unittest

from core.formatting import format_compact_number, format_de_date, format_de_number
from core.report_config import normalize_report_settings, validate_accent_color, validated_logo_data_uri
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

    def test_report_accent_rejects_low_contrast_and_invalid_values(self):
        self.assertEqual(validate_accent_color("#000000"), "#4F46E5")
        self.assertEqual(validate_accent_color("not-a-color"), "#4F46E5")

    def test_report_accent_accepts_valid_mid_tone(self):
        self.assertEqual(validate_accent_color("#2277AA"), "#2277AA")

    def test_logo_accepts_real_png_signature_only(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        uri = validated_logo_data_uri(png)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        with self.assertRaises(ValueError):
            validated_logo_data_uri(b"<svg><script>alert(1)</script></svg>")

    def test_report_settings_are_bounded(self):
        settings = normalize_report_settings({"company_name": "A" * 500, "show_kpis": False})
        self.assertEqual(len(settings["company_name"]), 160)
        self.assertFalse(settings["show_kpis"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
