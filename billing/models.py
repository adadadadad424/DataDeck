"""Small, provider-neutral billing domain models."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass


USER_ID_NAMESPACE = uuid.UUID("96bea3c7-970e-48db-9395-263785819557")
VALID_PLANS = frozenset({"free", "beta", "pro"})
VALID_SUBSCRIPTION_STATUSES = frozenset(
    {"active", "trialing", "past_due", "canceled", "unpaid", "incomplete", "incomplete_expired", "paused"}
)


def stable_user_id(issuer: str, subject: str) -> str:
    """Derive a non-secret internal ID from the stable OIDC issuer/subject pair."""
    normalized_issuer = issuer.strip().rstrip("/").casefold()
    normalized_subject = subject.strip()
    if not normalized_issuer or not normalized_subject:
        raise ValueError("OIDC issuer and subject are required")
    return str(uuid.uuid5(USER_ID_NAMESPACE, f"{normalized_issuer}\n{normalized_subject}"))


@dataclass(frozen=True)
class Identity:
    user_id: str
    issuer: str
    subject: str
    email: str
    beta_access: bool = False


@dataclass(frozen=True)
class BillingUser:
    user_id: str
    email: str
    oidc_issuer: str
    oidc_subject: str
    beta_access: bool = False
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    plan: str = "free"
    subscription_status: str | None = None
    current_period_end: dt.datetime | None = None
    cancel_at_period_end: bool = False
    last_stripe_event_created: int = 0
    last_synced_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

