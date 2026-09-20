"""Production controls that do not contain product or UI business logic."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import MutableMapping


APP_VERSION = "0.8.0-beta"
VALID_ENVIRONMENTS = {"development", "testing", "production"}
SENSITIVE_SESSION_KEYS = {
    "raw_df",
    "data_source",
    "data_signature",
    "last_upload_signature",
    "column_mapping",
    "ai_insights",
    "ai_insights_key",
    "ai_insights_source",
    "ai_insights_created_at",
    "pdf_bytes",
    "pdf_filename",
    "pdf_context_key",
    "revenue_only_mode",
    "min_gain_filter",
    "min_margin_filter",
    "category_filter",
    "ai_in_progress",
    "pdf_in_progress",
    "last_ai_started",
    "last_pdf_started",
    "last_ai_context",
    "last_pdf_context",
    "auth_audit_subject",
    "auth_denied_logged",
    "billing_checkout_url",
    "billing_return_synced",
}


def app_environment() -> str:
    value = os.getenv("APP_ENV", "development").strip().lower()
    return value if value in VALID_ENVIRONMENTS else "invalid"


def auth_required() -> bool:
    configured = os.getenv("AUTH_REQUIRED")
    if configured is None:
        return app_environment() == "production"
    return configured.strip().lower() in {"1", "true", "yes", "on"}


def approved_users() -> set[str]:
    raw = os.getenv("BETA_APPROVED_USERS", "")
    return {
        item.strip().casefold()
        for item in raw.split(",")
        if item.strip()
    }


def production_config_errors() -> list[str]:
    errors = []
    environment = app_environment()
    if environment == "invalid":
        errors.append("APP_ENV muss development, testing oder production sein.")
    if environment == "production":
        if not auth_required():
            errors.append("AUTH_REQUIRED darf in production nicht deaktiviert sein.")
        if not approved_users():
            errors.append("BETA_APPROVED_USERS muss mindestens einen Beta-Zugang enthalten.")
        required = (
            "GEMINI_API_KEY", "OIDC_CLIENT_ID", "OIDC_REDIRECT_URI",
            "OIDC_SERVER_METADATA_URL",
            "LEGAL_IMPRINT_URL", "LEGAL_PRIVACY_URL", "LEGAL_TERMS_URL",
            "BETA_FEEDBACK_URL",
        )
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            errors.append("Fehlende Produktionskonfiguration: " + ", ".join(missing) + ".")
        try:
            from billing.config import BillingConfig, billing_enabled

            if billing_enabled():
                BillingConfig.from_env()
        except ValueError as error:
            errors.append("Billing-Konfiguration ungültig: " + str(error) + ".")
    return errors


def is_approved_user(email: str | None) -> bool:
    return bool(email and email.casefold() in approved_users())


def anonymized_user_id(subject: str | None, email: str | None = None) -> str:
    identity = subject or email or "anonymous"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def dataset_hash(file_content: bytes) -> str:
    return hashlib.sha256(file_content).hexdigest()


def action_allowed(last_run: float | None, cooldown_seconds: float, now: float | None = None) -> bool:
    if last_run is None:
        return True
    current = time.monotonic() if now is None else now
    return current - last_run >= cooldown_seconds


def clear_sensitive_session(state: MutableMapping) -> None:
    """Remove all uploaded or derived customer data from one session."""
    for key in SENSITIVE_SESSION_KEYS:
        state.pop(key, None)


def safe_exception_name(error: BaseException) -> str:
    """Return only the exception class, never its potentially sensitive message."""
    return type(error).__name__
