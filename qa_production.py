"""Production configuration and deployment artifact checks."""

from __future__ import annotations

import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from production_start import build_streamlit_auth_toml, validate_production_environment


def valid_environment() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "AUTH_REQUIRED": "true",
        "BETA_APPROVED_USERS": "alpha@example.org,beta@example.org",
        "GEMINI_API_KEY": "test-value-never-used",
        "OIDC_CLIENT_ID": "client-id",
        "OIDC_CLIENT_SECRET": "client-secret",
        "OIDC_COOKIE_SECRET": "x" * 48,
        "OIDC_REDIRECT_URI": "https://beta.example.org/oauth2callback",
        "OIDC_SERVER_METADATA_URL": "https://accounts.google.com/.well-known/openid-configuration",
        "LEGAL_IMPRINT_URL": "https://example.org/impressum",
        "LEGAL_PRIVACY_URL": "https://example.org/datenschutz",
        "LEGAL_TERMS_URL": "https://example.org/nutzungsbedingungen",
        "BETA_FEEDBACK_URL": "https://example.org/feedback",
    }


class ProductionTests(unittest.TestCase):
    def test_missing_configuration_fails_closed(self):
        errors = validate_production_environment({"APP_ENV": "production", "AUTH_REQUIRED": "true"})
        self.assertGreaterEqual(len(errors), 10)

    def test_valid_configuration_passes(self):
        self.assertEqual(validate_production_environment(valid_environment()), [])

    def test_enabled_billing_requires_complete_matching_test_configuration(self):
        env = valid_environment()
        env["BILLING_ENABLED"] = "true"
        errors = validate_production_environment(env)
        self.assertTrue(any("Billing configuration invalid" in error for error in errors))

        env.update(
            {
                "STRIPE_MODE": "test",
                "DATABASE_URL": "postgresql://billing.example.org/datadeck",
                "STRIPE_SECRET_KEY": "sk_live_wrong_mode",
                "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
                "APP_BASE_URL": "https://beta.example.org",
            }
        )
        errors = validate_production_environment(env)
        self.assertTrue(any("must match test mode" in error for error in errors))

    def test_http_and_bad_redirect_are_rejected(self):
        env = valid_environment()
        env["OIDC_REDIRECT_URI"] = "http://beta.example.org/callback"
        errors = validate_production_environment(env)
        self.assertTrue(any("HTTPS" in error for error in errors))
        self.assertTrue(any("oauth2callback" in error for error in errors))

    def test_generated_oidc_config_is_valid_toml_without_token_exposure(self):
        env = valid_environment()
        content = build_streamlit_auth_toml(env)
        parsed = tomllib.loads(content)
        self.assertEqual(parsed["auth"]["client_id"], "client-id")
        self.assertEqual(parsed["auth"]["expose_tokens"], [])

    def test_deployment_files_contain_no_secret_values(self):
        render = Path("render.yaml").read_text(encoding="utf-8")
        docker = Path("Dockerfile").read_text(encoding="utf-8")
        self.assertIn("sync: false", render)
        self.assertNotIn("client-secret", render + docker)
        self.assertIn("python\", \"production_start.py", docker)

    def test_production_ui_uses_server_side_entitlement(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("entitlement_for(billing_user).has_access", source)
        self.assertIn("if is_production:", source)

    def test_closed_beta_has_honest_public_placeholder_pages(self):
        source = Path("main.py").read_text(encoding="utf-8")
        for page in ("impressum", "datenschutz", "nutzungsbedingungen", "feedback"):
            self.assertIn(f'"{page}"', source)
        self.assertIn("keine Rechtsberatung", source)
        self.assertIn('"werden nur berechnete und aggregierte Kennzahlen übertragen, niemals "', source)
        self.assertIn('"die vollständigen Rohdaten des Uploads."', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
