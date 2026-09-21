"""Fail-closed production entry point for the DataDeck container."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from billing.config import BillingConfig, billing_enabled
from billing.migrate import verify_migrations


REQUIRED_PRODUCTION_ENV = (
    "BETA_APPROVED_USERS",
    "GEMINI_API_KEY",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_COOKIE_SECRET",
    "OIDC_REDIRECT_URI",
    "OIDC_SERVER_METADATA_URL",
    "LEGAL_IMPRINT_URL",
    "LEGAL_PRIVACY_URL",
    "LEGAL_TERMS_URL",
    "BETA_FEEDBACK_URL",
    "DATABASE_URL",
)


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def validate_production_environment(environ: dict[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    errors = []
    if env.get("APP_ENV", "").strip().lower() != "production":
        errors.append("APP_ENV must be production.")
    if env.get("AUTH_REQUIRED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        errors.append("AUTH_REQUIRED must be true.")
    for name in REQUIRED_PRODUCTION_ENV:
        if not env.get(name, "").strip():
            errors.append(f"{name} is required.")

    approved = [item.strip() for item in env.get("BETA_APPROVED_USERS", "").split(",") if item.strip()]
    if approved and any("@" not in item or item.startswith("@") or item.endswith("@") for item in approved):
        errors.append("BETA_APPROVED_USERS contains an invalid email address.")
    if env.get("OIDC_COOKIE_SECRET") and len(env["OIDC_COOKIE_SECRET"]) < 32:
        errors.append("OIDC_COOKIE_SECRET must contain at least 32 characters.")

    url_names = (
        "OIDC_REDIRECT_URI",
        "OIDC_SERVER_METADATA_URL",
        "LEGAL_IMPRINT_URL",
        "LEGAL_PRIVACY_URL",
        "LEGAL_TERMS_URL",
        "BETA_FEEDBACK_URL",
    )
    for name in url_names:
        value = env.get(name, "").strip()
        if value and not _is_https_url(value):
            errors.append(f"{name} must be an HTTPS URL without embedded credentials.")
    redirect = env.get("OIDC_REDIRECT_URI", "").strip()
    if redirect and not redirect.rstrip("/").endswith("/oauth2callback"):
        errors.append("OIDC_REDIRECT_URI must end with /oauth2callback.")
    database_url = env.get("DATABASE_URL", "").strip()
    if database_url and not database_url.startswith(("postgresql://", "postgres://")):
        errors.append("DATABASE_URL must be a PostgreSQL URL.")
    if billing_enabled(env):
        try:
            BillingConfig.from_env(env)
        except ValueError as error:
            errors.append(f"Billing configuration invalid: {error}.")
    return errors


def build_streamlit_auth_toml(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    values = {
        "redirect_uri": env["OIDC_REDIRECT_URI"],
        "cookie_secret": env["OIDC_COOKIE_SECRET"],
        "client_id": env["OIDC_CLIENT_ID"],
        "client_secret": env["OIDC_CLIENT_SECRET"],
        "server_metadata_url": env["OIDC_SERVER_METADATA_URL"],
    }
    lines = ["[auth]"]
    lines.extend(f"{key} = {json.dumps(value)}" for key, value in values.items())
    lines.append("expose_tokens = []")
    return "\n".join(lines) + "\n"


def write_streamlit_auth_config(path: Path, environ: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_streamlit_auth_toml(environ), encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    errors = validate_production_environment()
    if errors:
        print("DataDeck production startup refused:", flush=True)
        for error in errors:
            print(f"- {error}", flush=True)
        raise SystemExit(78)

    try:
        schema = verify_migrations(os.environ["DATABASE_URL"])
    except Exception as error:
        print(
            "DataDeck production startup refused: database readiness check failed "
            f"({type(error).__name__}).",
            flush=True,
        )
        raise SystemExit(78) from error
    print(
        json.dumps({
            "event": "DATABASE_READY",
            "migration_count": schema["migrations"],
            "foreign_key_count": schema["foreign_keys"],
            "index_count": schema["indexes"],
        }),
        flush=True,
    )

    write_streamlit_auth_config(Path(".streamlit/secrets.toml"))
    for name in ("OIDC_CLIENT_SECRET", "OIDC_COOKIE_SECRET"):
        os.environ.pop(name, None)

    port = os.getenv("PORT", "8501")
    os.execvp(
        "streamlit",
        [
            "streamlit", "run", "main.py",
            "--server.address=0.0.0.0",
            f"--server.port={port}",
            "--server.headless=true",
        ],
    )


if __name__ == "__main__":
    main()
