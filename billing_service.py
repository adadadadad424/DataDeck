"""Independent HTTP endpoint for Stripe webhooks."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from stripe import SignatureVerificationError

from billing.config import BillingConfig
from billing.service import BillingService, _value
from billing.stripe_gateway import StripeGateway


logger = logging.getLogger("DataDeckBilling")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    app_instance.state.billing_config = BillingConfig.from_env(require_webhook=True)
    yield


app = FastAPI(title="DataDeck Billing", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, bool]:
    started = time.perf_counter()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Invalid signature")
    config = request.app.state.billing_config
    payload = await request.body()
    try:
        event = StripeGateway.verify_event(payload, stripe_signature, config.webhook_secret)
    except (ValueError, SignatureVerificationError) as error:
        logger.warning("WEBHOOK_FAILED error_type=%s", type(error).__name__)
        raise HTTPException(status_code=400, detail="Invalid signature") from None
    event_id = str(_value(event, "id", "invalid"))
    event_type = str(_value(event, "type", "unknown"))
    try:
        processed = BillingService(config).handle_verified_event(event)
    except Exception as error:
        logger.error(
            "WEBHOOK_FAILED event_id=%s event_type=%s error_type=%s duration_ms=%s",
            event_id,
            event_type,
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
