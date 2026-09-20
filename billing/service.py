"""Checkout, portal and webhook orchestration."""

from __future__ import annotations

import datetime as dt
from typing import Any

from .config import BillingConfig
from .entitlements import entitlement_for
from .models import BillingUser, Identity
from .store import PostgresBillingStore
from .stripe_gateway import StripeGateway


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _subscription_id_from_invoice(invoice: Any) -> str | None:
    direct = _value(invoice, "subscription")
    if direct:
        return str(direct)
    parent = _value(invoice, "parent", {}) or {}
    details = _value(parent, "subscription_details", {}) or {}
    subscription = _value(details, "subscription")
    return str(subscription) if subscription else None


def _timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromtimestamp(int(value), tz=dt.UTC)


class BillingService:
    def __init__(
        self,
        config: BillingConfig,
        store: PostgresBillingStore | Any | None = None,
        stripe_gateway: StripeGateway | Any | None = None,
    ):
        self.config = config
        self.store = store or PostgresBillingStore(config.database_url)
        self.stripe = stripe_gateway or StripeGateway(config.stripe_secret_key)

    def register_user(self, identity: Identity) -> BillingUser:
        return self.store.upsert_identity(identity)

    def create_checkout_url(self, identity: Identity) -> str:
        user = self.register_user(identity)
        if entitlement_for(user).has_active_pro:
            raise ValueError("User already has an active subscription")
        if not user.stripe_customer_id:
            customer = self.stripe.create_customer(user_id=user.user_id, email=user.email)
            user = self.store.bind_customer(user.user_id, str(_value(customer, "id")))
        session = self.stripe.create_checkout(
            user_id=user.user_id,
            customer_id=user.stripe_customer_id,
            price_id=self.config.price_monthly,
            success_url=f"{self.config.app_base_url}/?billing=confirming",
            cancel_url=f"{self.config.app_base_url}/?billing=canceled",
        )
        url = _value(session, "url")
        if not url:
            raise RuntimeError("Stripe returned no Checkout URL")
        return str(url)

    def create_portal_url(self, identity: Identity) -> str:
        user = self.register_user(identity)
        if not user.stripe_customer_id:
            raise ValueError("No Stripe customer exists for this user")
        session = self.stripe.create_portal(
            customer_id=user.stripe_customer_id,
            return_url=f"{self.config.app_base_url}/?billing=returned",
        )
        url = _value(session, "url")
        if not url:
            raise RuntimeError("Stripe returned no Portal URL")
        return str(url)

    def sync_user(self, identity: Identity) -> BillingUser:
        user = self.register_user(identity)
        if not user.stripe_subscription_id or not user.stripe_customer_id:
            return user
        subscription = self.stripe.retrieve_subscription(user.stripe_subscription_id)
        customer_id = str(_value(subscription, "customer", ""))
        metadata = _value(subscription, "metadata", {}) or {}
        if customer_id != user.stripe_customer_id or str(_value(metadata, "datadeck_user_id", "")) != user.user_id:
            raise PermissionError("Stripe subscription does not belong to this user")
        return self.store.update_subscription_snapshot(
            user_id=user.user_id,
            customer_id=customer_id,
            subscription_id=user.stripe_subscription_id,
            status=str(_value(subscription, "status", "incomplete")),
            current_period_end=_timestamp(_value(subscription, "current_period_end")),
            cancel_at_period_end=bool(_value(subscription, "cancel_at_period_end", False)),
        )

    def handle_verified_event(self, event: Any) -> bool:
        event_id = str(_value(event, "id", ""))
        event_type = str(_value(event, "type", ""))
        event_created = int(_value(event, "created", 0))
        event_data = _value(_value(event, "data", {}), "object", {})
        if not event_id or not event_type or not event_created:
            raise ValueError("Incomplete Stripe event")

        def mutation(connection) -> None:
            if event_type == "checkout.session.completed":
                self._apply_checkout(connection, event_data, event_created)
            elif event_type.startswith("customer.subscription."):
                self._apply_subscription(connection, event_data, event_created)
            elif event_type in {"invoice.paid", "invoice.payment_failed"}:
                subscription_id = _subscription_id_from_invoice(event_data)
                if subscription_id:
                    subscription = self.stripe.retrieve_subscription(subscription_id)
                    self._apply_subscription(connection, subscription, event_created)

        return self.store.process_event_once(event_id, event_type, event_created, mutation)

    def _apply_checkout(self, connection, session: Any, event_created: int) -> None:
        user_id = str(_value(session, "client_reference_id", ""))
        customer_id = str(_value(session, "customer", ""))
        if not user_id or not customer_id:
            raise ValueError("Checkout session has no DataDeck user/customer mapping")
        self.store.bind_customer_in_transaction(connection, user_id, customer_id)
        subscription_id = _value(session, "subscription")
        if subscription_id:
            subscription = self.stripe.retrieve_subscription(str(subscription_id))
            self._apply_subscription(connection, subscription, event_created)

    def _apply_subscription(self, connection, event_object: Any, event_created: int) -> None:
        subscription_id = str(_value(event_object, "id", ""))
        if not subscription_id:
            raise ValueError("Subscription event has no subscription ID")
        latest = self.stripe.retrieve_subscription(subscription_id)
        customer_id = str(_value(latest, "customer", ""))
        metadata = _value(latest, "metadata", {}) or {}
        user_id = str(_value(metadata, "datadeck_user_id", ""))
        if not user_id or not customer_id:
            raise ValueError("Subscription has no DataDeck user/customer mapping")
        self.store.apply_subscription_in_transaction(
            connection,
            user_id=user_id,
            customer_id=customer_id,
            subscription_id=subscription_id,
            status=str(_value(latest, "status", "incomplete")),
            current_period_end=_timestamp(_value(latest, "current_period_end")),
            cancel_at_period_end=bool(_value(latest, "cancel_at_period_end", False)),
            event_created=event_created,
        )
