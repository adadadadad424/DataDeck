"""Independent HTTP endpoint for Stripe webhooks."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from stripe import SignatureVerificationError

from billing.config import BillingConfig
from billing.service import BillingService, _value
from billing.stripe_gateway import StripeGateway
from core.database import connect_postgres
from core.security_controls import SecurityLimitError, guarded_operation, sanitize_log_value


logger = logging.getLogger("DataDeckBilling")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    app_instance.state.billing_config = BillingConfig.from_env(require_webhook=True)
    yield


app = FastAPI(title="DataDeck Billing", docs_url=None, redoc_url=None, lifespan=lifespan)


def _max_webhook_bytes() -> int:
    try:
        return max(16_384, min(int(os.getenv("MAX_WEBHOOK_BODY_BYTES", "262144")), 1_048_576))
    except ValueError:
        return 262_144


async def _bounded_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail="Payload too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid request") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="Payload too large")
    return bytes(body)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.headers.get("x-forwarded-proto", "").casefold() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readiness")
def readiness(request: Request):
    try:
        config = request.app.state.billing_config
        with connect_postgres(config.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}


@app.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, bool]:
    started = time.perf_counter()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Invalid signature")
    config = request.app.state.billing_config
    try:
        remote = request.client.host if request.client else "unknown"
        with guarded_operation("webhook", remote):
            payload = await _bounded_body(request, _max_webhook_bytes())
            try:
                event = StripeGateway.verify_event(payload, stripe_signature, config.webhook_secret)
            except (ValueError, SignatureVerificationError) as error:
                logger.warning("WEBHOOK_INVALID error_type=%s", type(error).__name__)
                raise HTTPException(status_code=400, detail="Invalid signature") from None
            event_id = sanitize_log_value(_value(event, "id", "invalid"), 80)
            event_type = sanitize_log_value(_value(event, "type", "unknown"), 80)
            event_created = int(_value(event, "created", 0))
            now = int(time.time())
            if event_created <= 0 or event_created < now - 7 * 86_400 or event_created > now + 300:
                logger.warning("WEBHOOK_REJECTED reason=event_age")
                raise HTTPException(status_code=400, detail="Invalid event")
            processed = BillingService(config).handle_verified_event(event)
    except SecurityLimitError as error:
        logger.warning("RATE_LIMITED action=webhook")
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(error.retry_after)},
        ) from None
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "WEBHOOK_FAILED event_id=%s event_type=%s error_type=%s duration_ms=%s",
            locals().get("event_id", "unknown"),
            locals().get("event_type", "unknown"),
            type(error).__name__,
            round((time.perf_counter() - started) * 1000),
        )
        raise HTTPException(status_code=503, detail="Processing failed") from None
    logger.info(
        "WEBHOOK_SUCCESS event_id=%s event_type=%s status=%s duration_ms=%s",
        event_id,
        event_type,
        "processed" if processed else "duplicate",
        round((time.perf_counter() - started) * 1000),
    )
    return {"received": True}
