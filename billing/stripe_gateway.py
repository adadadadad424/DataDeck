"""Narrow Stripe SDK adapter; no UI code and no persistence."""

from __future__ import annotations

import time
from typing import Any

import stripe


class StripeGateway:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def create_customer(self, *, user_id: str, email: str) -> dict[str, Any]:
        return stripe.Customer.create(
            api_key=self.secret_key,
            email=email,
            metadata={"datadeck_user_id": user_id},
            idempotency_key=f"datadeck-customer-{user_id}",
        )

    def create_checkout(
        self,
        *,
        user_id: str,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        bucket = int(time.time() // 600)
        return stripe.checkout.Session.create(
            api_key=self.secret_key,
            customer=customer_id,
            client_reference_id=user_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"datadeck_user_id": user_id},
            subscription_data={"metadata": {"datadeck_user_id": user_id}},
            idempotency_key=f"datadeck-checkout-{user_id}-{bucket}",
        )

    def create_portal(self, *, customer_id: str, return_url: str) -> dict[str, Any]:
        return stripe.billing_portal.Session.create(
            api_key=self.secret_key,
            customer=customer_id,
            return_url=return_url,
        )

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        return stripe.Subscription.retrieve(subscription_id, api_key=self.secret_key)

    @staticmethod
    def verify_event(payload: bytes, signature: str, webhook_secret: str) -> dict[str, Any]:
        return stripe.Webhook.construct_event(payload, signature, webhook_secret)

