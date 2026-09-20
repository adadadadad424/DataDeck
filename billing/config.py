"""Billing configuration and test/live separation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


TRUE_VALUES = {"1", "true", "yes", "on"}


def billing_enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("BILLING_ENABLED", "false").strip().lower() in TRUE_VALUES


@dataclass(frozen=True)
class BillingConfig:
    mode: str
    database_url: str
    stripe_secret_key: str
    webhook_secret: str
    price_monthly: str
    app_base_url: str

    @classmethod
    def from_env(
        cls,
        environ: dict[str, str] | None = None,
        *,
        require_webhook: bool = False,
    ) -> "BillingConfig":
        env = os.environ if environ is None else environ
        config = cls(
            mode=env.get("STRIPE_MODE", "test").strip().lower(),
            database_url=env.get("DATABASE_URL", "").strip(),
            stripe_secret_key=env.get("STRIPE_SECRET_KEY", "").strip(),
            webhook_secret=env.get("STRIPE_WEBHOOK_SECRET", "").strip(),
            price_monthly=env.get("STRIPE_PRICE_PRO_MONTHLY", "").strip(),
            app_base_url=env.get("APP_BASE_URL", "").strip().rstrip("/"),
        )
        errors = config.errors(require_webhook=require_webhook)
        if errors:
            raise ValueError("; ".join(errors))
        return config

    def errors(self, *, require_webhook: bool = False) -> list[str]:
        errors: list[str] = []
        if self.mode not in {"test", "live"}:
            errors.append("STRIPE_MODE must be test or live")
        expected_key_prefix = "sk_live_" if self.mode == "live" else "sk_test_"
        if not self.stripe_secret_key.startswith(expected_key_prefix):
            errors.append(f"STRIPE_SECRET_KEY must match {self.mode} mode")
        if require_webhook and not self.webhook_secret.startswith("whsec_"):
            errors.append("STRIPE_WEBHOOK_SECRET must start with whsec_")
        if not self.price_monthly.startswith("price_"):
            errors.append("STRIPE_PRICE_PRO_MONTHLY must start with price_")
        parsed = urlparse(self.app_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            errors.append("APP_BASE_URL must be an HTTPS URL without credentials")
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            errors.append("DATABASE_URL must be PostgreSQL")
        return errors
