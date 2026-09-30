"""Fokussierte Regressionstests fuer darstellende UI-Logik."""

import datetime
import base64
import unittest
from pathlib import Path

import pandas as pd

from core.formatting import format_compact_number, format_de_date, format_de_number
from core.report_config import normalize_report_settings, validate_accent_color, validated_logo_data_uri
from core.theme import inject_theme_css, get_theme
from main import (
    PREVIEW_MAX_ROWS,
    _compute_insight_key,
    _data_preview_table,
    _mapping_requires_review,
    _monthly_chart_ticks,
    _stable_mapping_key,
)


class UIQualityTests(unittest.TestCase):
    def test_consultant_flow_uses_consolidated_optional_areas(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('st.expander("Details & Prüfung"', source)
        self.assertIn('st.expander("Erweiterte Optionen"', source)
        self.assertNotIn('st.expander("Filter anpassen"', source)
        self.assertNotIn('st.expander("Szenario rechnen"', source)
        self.assertNotIn('st.expander("Wichtige Grafiken"', source)

    def test_export_has_one_clear_format_choice_and_action(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('"Was möchten Sie erstellen?"', source)
        self.assertIn('["PDF-Report", "PowerPoint-Präsentation", "Beide erstellen"]', source)
        self.assertIn('key="generate_export_btn"', source)
        self.assertNotIn('key="generate_pdf_btn"', source)
        self.assertNotIn('key="generate_pptx_btn"', source)
        self.assertIn("können in Keynote geöffnet oder importiert werden", source)

    def test_modern_controls_share_theme_tokens(self):
        for name in ("light", "dark"):
            with self.subTest(theme=name):
                theme = get_theme(name)
                css = inject_theme_css(theme)
                self.assertIn('[data-testid="stSegmentedControl"]', css)
                self.assertIn(f"background: {theme['surface_alt']} !important", css)
                self.assertIn('button[data-selected="true"]', css)
                self.assertIn(f"border-color: {theme['accent']} !important", css)
                self.assertIn(f"color: {theme['text']} !important", css)
                self.assertIn("min-height: 42px", css)

    def test_expander_states_use_current_theme(self):
        for name in ("light", "dark"):
            with self.subTest(theme=name):
                theme = get_theme(name)
                css = inject_theme_css(theme)
                start = css.index('[data-testid="stExpander"] details,')
                block = css[start:css.index("}", start)]
                for selector in ("details[open] > summary", "summary:hover", "summary:focus", "summary:active"):
                    self.assertIn(selector, block)
                self.assertIn(f"background-color: {theme['surface']} !important", block)
                self.assertIn(f"color: {theme['text']} !important", block)
                self.assertIn('summary:focus-visible', css)

    def test_text_area_uses_current_theme(self):
        for name in ("light", "dark"):
            with self.subTest(theme=name):
                theme = get_theme(name)
                css = inject_theme_css(theme)
                start = css.index('[data-testid="stTextArea"] textarea')
                block = css[start:css.index("}", start)]
                self.assertIn(f"background-color: {theme['surface']} !important", block)
                self.assertIn(f"color: {theme['text']} !important", block)
                self.assertIn(f"border: 1px solid {theme['border']} !important", block)
                self.assertIn('[data-testid="stTextArea"] div[data-baseweb="base-input"]:focus-within', css)
                self.assertIn(f"box-shadow: 0 0 0 1px {theme['accent']} !important", css)

    def test_assistant_card_is_visually_distinct(self):
        theme = get_theme("light")
        css = inject_theme_css(theme)
        self.assertIn(".dd-card.assistant", css)
        self.assertIn(f"background: {theme['accent_soft']}", css)
        self.assertIn(".dd-card.assistant ol", css)

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

    def test_monthly_chart_labels_are_compact_and_german(self):
        values = [datetime.date(2025, month, 1) for month in range(1, 13)]
        ticks, labels = _monthly_chart_ticks(values)
        self.assertLessEqual(len(ticks), 4)
        self.assertEqual(labels[0], "Jan 25")
        self.assertEqual(labels[-1], "Okt 25")
        self.assertNotIn("Oct", labels)

    def test_monthly_chart_uses_clean_financial_lines(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count('mode="lines"'), 2)
        self.assertNotIn('mode="lines+markers"', source)
        self.assertIn('hovermode="x unified"', source)

    def test_raw_preview_is_hard_limited(self):
        frame = pd.DataFrame({"Wert": range(PREVIEW_MAX_ROWS + 25)})
        html = _data_preview_table(frame, max_rows=10_000)
        self.assertEqual(html.count("<tr>"), PREVIEW_MAX_ROWS + 1)

    def test_plan_toggle_does_not_make_factual_insight_stale(self):
        kpis = {
            "gesamt_umsatz": 1000.0,
            "gesamt_gewinn": 250.0,
            "anzahl_zeilen": 4,
            "kategorien_daten": pd.DataFrame({"Kategorie_Clean": ["A"], "Gewinn_Clean": [250.0]}),
            "financial_aggregation_available": True,
        }
        free_key = _compute_insight_key(kpis, 20.0, "Allgemein", False, "de")
        premium_key = _compute_insight_key(kpis, 20.0, "Allgemein", True, "de")
        self.assertEqual(free_key, premium_key)

    def test_report_branding_does_not_force_ai_insight_stale(self):
        source = Path("main.py").read_text(encoding="utf-8")
        start = source.index('if st.form_submit_button("Report-Einstellungen speichern"')
        end = source.index('st.success("Report-Einstellungen gespeichert.")', start)
        form_block = source[start:end]
        self.assertNotIn("st.session_state.ai_insights_key = None", form_block)

    def test_mobile_heading_has_bounded_fixed_size(self):
        css = inject_theme_css(get_theme("light"))
        self.assertIn("@media (max-width: 600px)", css)
        self.assertIn("h1 { font-size: 2rem !important", css)

    def test_performance_instrumentation_and_large_xlsx_hint_exist(self):
        source = Path("main.py").read_text(encoding="utf-8")
        for stage in ("import", "mapping", "analysis", "ai", "export_pdf", "export_pptx", "total"):
            self.assertIn(f'_record_performance_timing("{stage}"', source)
        self.assertIn("Für maximale Geschwindigkeit empfehlen wir CSV.", source)
        self.assertIn('"import_cache_key": None', source)

    def test_log_event_writes_to_logger(self):
        source = Path("main.py").read_text(encoding="utf-8")
        start = source.index("def _log_event(")
        end = source.index("def _record_performance_timing(", start)
        log_block = source[start:end]
        self.assertIn("logger.log(", log_block)

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
        settings = normalize_report_settings({
            "company_name": "A" * 500,
            "client_name": "B" * 500,
            "show_kpis": False,
            "language": "en",
            "ppt_deck_style": "short",
            "ppt_audience": "finance",
            "ppt_speaker_notes": True,
        })
        self.assertEqual(len(settings["company_name"]), 160)
        self.assertEqual(len(settings["client_name"]), 160)
        self.assertFalse(settings["show_kpis"])
        self.assertEqual(settings["language"], "en")
        self.assertEqual(settings["ppt_deck_style"], "short")
        self.assertEqual(settings["ppt_audience"], "finance")
        self.assertTrue(settings["ppt_speaker_notes"])

    def test_report_language_falls_back_to_german(self):
        settings = normalize_report_settings({
            "language": "fr",
            "ppt_deck_style": "tiny",
            "ppt_audience": "legal",
        })
        self.assertEqual(settings["language"], "de")
        self.assertEqual(settings["ppt_deck_style"], "full")
        self.assertEqual(settings["ppt_audience"], "management")


if __name__ == "__main__":
    unittest.main(verbosity=2)
