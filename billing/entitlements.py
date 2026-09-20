"""One central decision for beta and paid access."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .models import BillingUser


PAID_ACCESS_STATUSES = frozenset({"active", "trialing"})


@dataclass(frozen=True)
class Entitlement:
    has_access: bool
    has_active_pro: bool
    plan: str
    reason: str


def entitlement_for(user: BillingUser, now: dt.datetime | None = None) -> Entitlement:
    """Resolve access without browser state or redirect parameters."""
    del now  # Kept for future time-bound grace rules without changing callers.
    active_pro = user.subscription_status in PAID_ACCESS_STATUSES
    if user.beta_access:
        return Entitlement(True, active_pro, "pro" if active_pro else "beta", "beta_access")
    if active_pro:
        return Entitlement(True, True, "pro", "active_subscription")
    return Entitlement(False, False, "free", "no_entitlement")


def premium_feature_access(*, billing_active: bool, user: BillingUser | None) -> bool:
    """Keep the closed beta open, but fail closed when enabled billing is unavailable."""
    if not billing_active:
        return True
    return bool(user is not None and entitlement_for(user).has_access)
