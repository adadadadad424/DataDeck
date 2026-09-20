"""Focused beta-readiness checks for isolation and hostile input boundaries."""

from __future__ import annotations

import io
import os
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pandas as pd
from streamlit.testing.v1 import AppTest

from core.ai_insights import _build_prompt, generate_local_summary
from core.analysis import METRIC_LIMITED, calculate_kpis
from core.data_processing import assess_data_quality, clean_and_prepare_data, load_and_validate_file
from core.report_builder import APP_VERSION, _template, generate_pdf
from core.runtime_security import (
    action_allowed,
    clear_sensitive_session,
    dataset_hash,
    production_config_errors,
)


@contextmanager
def environment(**values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def prepared(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    clean, warnings = clean_and_prepare_data(frame)
    quality = assess_data_quality(frame, clean, warnings)
    kpis = calculate_kpis(clean, {**warnings, "data_quality": quality})
    return clean, quality, kpis


class BetaSecurityTests(unittest.TestCase):
    def test_production_fails_closed_without_auth_and_allowlist(self):
        with environment(APP_ENV="production", AUTH_REQUIRED="false", BETA_APPROVED_USERS=""):
            errors = production_config_errors()
        self.assertGreaterEqual(len(errors), 2)

    def test_logout_cleanup_removes_customer_data_only(self):
        state = {
            "raw_df": pd.DataFrame({"secret": [1]}),
            "ai_insights": {"secret": "x"},
            "pdf_bytes": b"private",
            "column_mapping": {"umsatz": "secret"},
            "prepared_df_cache": pd.DataFrame({"derived_secret": [1]}),
            "pii_scan_cache": {"spalten_mit_treffern": ["secret"]},
            "kpi_cache": {"gesamt_umsatz": 1},
            "theme": "dark",
        }
        clear_sensitive_session(state)
        self.assertEqual(state, {"theme": "dark"})

    def test_same_filename_different_content_has_different_identity(self):
        self.assertNotEqual(dataset_hash(b"ALPHA_CORP"), dataset_hash(b"BETA_CORP"))

    def test_action_cooldown(self):
        self.assertFalse(action_allowed(100.0, 10.0, now=105.0))
        self.assertTrue(action_allowed(100.0, 10.0, now=110.0))

    def test_rejects_oversized_upload_before_parsing(self):
        with environment(MAX_UPLOAD_SIZE_MB="1"):
            with self.assertRaisesRegex(ValueError, "Systemlimit"):
                load_and_validate_file(b"x" * (1024 * 1024 + 1), "large.csv", True)

    def test_rejects_invalid_extension_and_binary_csv(self):
        with self.assertRaisesRegex(ValueError, "CSV- oder XLSX"):
            load_and_validate_file(b"hello", "payload.txt", True)
        with self.assertRaisesRegex(ValueError, "Binärdaten"):
            load_and_validate_file(b"Umsatz\x00Gewinn", "payload.csv", True)

    def test_rejects_excessive_csv_columns(self):
        content = ((",".join(f"c{i}" for i in range(251))) + "\n" + (",".join("1" for _ in range(251)))).encode()
        with environment(MAX_DATASET_COLUMNS="250"):
            with self.assertRaisesRegex(ValueError, "Spaltenlimit"):
                load_and_validate_file(content, "wide.csv", True)

    def test_rejects_invalid_xlsx_and_zip_bomb_ratio(self):
        with self.assertRaisesRegex(ValueError, "XLSX"):
            load_and_validate_file(b"not-an-excel-file", "bad.xlsx", True)
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/worksheets/sheet1.xml", "A" * 2_000_000)
        with self.assertRaisesRegex(ValueError, "Kompressionsverhältnis"):
            load_and_validate_file(payload.getvalue(), "bomb.xlsx", True)

    def test_multiple_currencies_block_financial_aggregation(self):
        raw = pd.DataFrame({
            "Kategorie": ["EU", "US"],
            "Umsatz": ["€ 100", "$ 200"],
            "Gewinn": ["€ 20", "$ 50"],
        })
        _, quality, kpis = prepared(raw)
        self.assertTrue(quality["multiple_currencies"])
        self.assertFalse(kpis["financial_aggregation_available"])
        self.assertEqual(kpis["metrics"]["umsatz"]["status"], METRIC_LIMITED)
        self.assertEqual(kpis["top_performer"], [])
        self.assertFalse(kpis["time_analysis"]["available"])

    def test_ai_prompt_omits_mixed_currency_totals(self):
        raw = pd.DataFrame({
            "Kategorie": ["EU", "US"],
            "Umsatz": ["€ 100", "$ 200"],
            "Gewinn": ["€ 20", "$ 50"],
        })
        _, _, kpis = prepared(raw)
        prompt = _build_prompt(kpis, 20.0, False, "SaaS")
        self.assertIn("weder berechnet noch geschätzt", prompt)
        self.assertNotIn("300,00", prompt)

    def test_pii_is_masked_from_ai_category_context(self):
        raw = pd.DataFrame({
            "Kategorie": ["max.mustermann@example.com"],
            "Umsatz": [100],
            "Gewinn": [20],
        })
        _, _, kpis = prepared(raw)
        prompt = _build_prompt(kpis, 20.0, False, "SaaS")
        self.assertNotIn("max.mustermann@example.com", prompt)

    def test_mixed_currency_pdf_is_generated_without_rankings(self):
        raw = pd.DataFrame({
            "Kategorie": ["ALPHA", "BETA"],
            "Umsatz": ["€ 100", "$ 200"],
            "Gewinn": ["€ 20", "$ 50"],
        })
        _, quality, kpis = prepared(raw)
        html = _template.render(
            date="18.09.2026", app_version=APP_VERSION, kpis=kpis, insights=None,
            niche="SaaS", revenue_only=False, data_quality=quality,
            column_mapping=kpis["column_mapping"], aggregation_limited=True,
        )
        self.assertNotIn("300,00", html)
        self.assertNotIn("70,00", html)
        self.assertNotIn("ALPHA</td>", html)
        pdf = generate_pdf(kpis, None, "SaaS", data_quality=quality)
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_parallel_analyses_keep_markers_separate(self):
        def run(marker: str, revenue: int):
            _, _, kpis = prepared(pd.DataFrame({
                "Kategorie": [marker], "Umsatz": [revenue], "Gewinn": [revenue / 2]
            }))
            return kpis["top_performer"][0]["Kategorie_Clean"], kpis["gesamt_umsatz"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda args: run(*args), [("ALPHA_CORP", 100), ("BETA_CORP", 200)] * 4))
        self.assertEqual(set(results), {("ALPHA_CORP", 100.0), ("BETA_CORP", 200.0)})

    def test_concurrent_ai_contexts_do_not_cross(self):
        def run(marker: str, revenue: int):
            _, _, kpis = prepared(pd.DataFrame({
                "Kategorie": [marker], "Umsatz": [revenue], "Gewinn": [revenue / 2]
            }))
            return marker, _build_prompt(kpis, 20.0, False, "SaaS"), generate_local_summary(kpis, 20.0)

        with ThreadPoolExecutor(max_workers=2) as pool:
            alpha, beta = list(pool.map(lambda args: run(*args), [("ALPHA_CORP", 100), ("BETA_CORP", 900)]))
        self.assertIn("ALPHA_CORP", alpha[1])
        self.assertNotIn("BETA_CORP", alpha[1])
        self.assertIn("BETA_CORP", beta[1])
        self.assertNotIn("ALPHA_CORP", beta[1])
        self.assertNotEqual(alpha[2]["zusammenfassung"], beta[2]["zusammenfassung"])

    def test_concurrent_pdfs_are_independent_in_memory(self):
        def run(marker: str, revenue: int):
            _, quality, kpis = prepared(pd.DataFrame({
                "Kategorie": [marker], "Umsatz": [revenue], "Gewinn": [revenue / 2]
            }))
            return generate_pdf(kpis, None, "SaaS", data_quality=quality)

        with ThreadPoolExecutor(max_workers=2) as pool:
            alpha_pdf, beta_pdf = list(pool.map(lambda args: run(*args), [("ALPHA_CORP", 100), ("BETA_CORP", 900)]))
        self.assertTrue(alpha_pdf.startswith(b"%PDF-"))
        self.assertTrue(beta_pdf.startswith(b"%PDF-"))
        self.assertNotEqual(alpha_pdf, beta_pdf)

    def test_streamlit_sessions_do_not_share_uploads_or_mapping(self):
        alpha = AppTest.from_file("main.py", default_timeout=30).run()
        beta = AppTest.from_file("main.py", default_timeout=30).run()
        alpha.file_uploader(key="file_uploader").set_value((
            "kunde.csv", b"Kategorie,Umsatz,Gewinn\nALPHA_CORP,100,20\n", "text/csv"
        )).run()
        beta.file_uploader(key="file_uploader").set_value((
            "kunde.csv", b"Kategorie,Umsatz,Gewinn\nBETA_CORP,900,90\n", "text/csv"
        )).run()
        alpha.button(key="import_review_start").click().run()
        beta.button(key="import_review_start").click().run()
        self.assertFalse(alpha.exception)
        self.assertFalse(beta.exception)
        self.assertEqual(alpha.session_state["raw_df"].iloc[0]["Kategorie"], "ALPHA_CORP")
        self.assertEqual(beta.session_state["raw_df"].iloc[0]["Kategorie"], "BETA_CORP")
        self.assertNotEqual(alpha.session_state["data_signature"], beta.session_state["data_signature"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
