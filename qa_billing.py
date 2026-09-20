"""Deterministic Stripe billing tests without real payments or secrets."""

from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from billing.config import BillingConfig
from billing.entitlements import entitlement_for
from billing.models import BillingUser, Identity, stable_user_id
from billing.service import BillingService
from billing_service import app
from core.runtime_security import clear_sensitive_session


def identity(user: str = "alpha") -> Identity:
    subject = f"subject-{user}"
    return Identity(
        user_id=stable_user_id("https://accounts.google.com", subject),
        issuer="https://accounts.google.com",
        subject=subject,
        email=f"{user}@example.org",
        beta_access=False,
    )


def config(mode: str = "test", key: str = "sk_test_placeholder") -> BillingConfig:
    return BillingConfig(
        mode=mode,
        database_url="postgresql://local/test",
        stripe_secret_key=key,
        webhook_secret="whsec_placeholder",
        price_monthly="price_test_monthly",
        app_base_url="https://beta.example.org",
    )


class FakeStore:
    def __init__(self):
        self.users: dict[str, BillingUser] = {}
        self.events: set[str] = set()

    def upsert_identity(self, item: Identity) -> BillingUser:
        current = self.users.get(item.user_id)
        user = BillingUser(
            user_id=item.user_id,
            email=item.email,
            oidc_issuer=item.issuer,
            oidc_subject=item.subject,
            beta_access=item.beta_access,
            stripe_customer_id=current.stripe_customer_id if current else None,
            stripe_subscription_id=current.stripe_subscription_id if current else None,
            plan=current.plan if current else ("beta" if item.beta_access else "free"),
            subscription_status=current.subscription_status if current else None,
            current_period_end=current.current_period_end if current else None,
            cancel_at_period_end=current.cancel_at_period_end if current else False,
            last_stripe_event_created=current.last_stripe_event_created if current else 0,
        )
        self.users[item.user_id] = user
        return user

    def get_user(self, user_id: str) -> BillingUser | None:
        return self.users.get(user_id)

    def bind_customer(self, user_id: str, customer_id: str) -> BillingUser:
        for existing in self.users.values():
            if existing.user_id != user_id and existing.stripe_customer_id == customer_id:
                raise PermissionError
        user = self.users[user_id]
        if user.stripe_customer_id not in {None, customer_id}:
            raise PermissionError
        updated = BillingUser(**{**user.__dict__, "stripe_customer_id": customer_id})
        self.users[user_id] = updated
        return updated

    def process_event_once(self, event_id, event_type, event_created, mutation):
        del event_type, event_created
        if event_id in self.events:
            return False
        try:
            mutation(self)
        except Exception:
            raise
        self.events.add(event_id)
        return True

    def bind_customer_in_transaction(self, connection, user_id, customer_id):
        del connection
        self.bind_customer(user_id, customer_id)

    def apply_subscription_in_transaction(self, connection, **values):
        del connection
        user = self.users[values["user_id"]]
        if user.stripe_customer_id not in {None, values["customer_id"]}:
            raise PermissionError
        if values["event_created"] < user.last_stripe_event_created:
            return
        plan = "pro" if values["status"] in {"active", "trialing"} else ("beta" if user.beta_access else "free")
        updated = BillingUser(
            **{
                **user.__dict__,
                "stripe_customer_id": values["customer_id"],
                "stripe_subscription_id": values["subscription_id"],
                "subscription_status": values["status"],
                "current_period_end": values["current_period_end"],
                "cancel_at_period_end": values["cancel_at_period_end"],
                "last_stripe_event_created": values["event_created"],
                "plan": plan,
            }
        )
        self.users[user.user_id] = updated

    def update_subscription_snapshot(self, **values):
        user = self.users[values["user_id"]]
        if user.stripe_customer_id != values["customer_id"]:
            raise PermissionError
        updated = BillingUser(
            **{
                **user.__dict__,
                "stripe_subscription_id": values["subscription_id"],
                "subscription_status": values["status"],
                "current_period_end": values["current_period_end"],
                "cancel_at_period_end": values["cancel_at_period_end"],
            }
        )
        self.users[user.user_id] = updated
        return updated


class FakeStripe:
    def __init__(self):
        self.subscriptions: dict[str, dict] = {}
        self.checkout_calls: list[dict] = []
        self.portal_calls: list[dict] = []
        self.down = False

    def create_customer(self, *, user_id, email):
        return {"id": f"cus_{user_id[:8]}", "email": email}

    def create_checkout(self, **kwargs):
        self.checkout_calls.append(kwargs)
        return {"url": "https://checkout.stripe.test/session"}

    def create_portal(self, **kwargs):
        self.portal_calls.append(kwargs)
        return {"url": "https://billing.stripe.test/portal"}

    def retrieve_subscription(self, subscription_id):
        if self.down:
            raise ConnectionError("provider down")
        return self.subscriptions[subscription_id]


def subscription(item: Identity, *, status="active", customer="cus_alpha", cancel=False):
    return {
        "id": "sub_alpha",
        "customer": customer,
        "status": status,
        "metadata": {"datadeck_user_id": item.user_id},
        "current_period_end": 1_900_000_000,
        "cancel_at_period_end": cancel,
    }


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.gateway = FakeStripe()
        self.service = BillingService(config(), self.store, self.gateway)
        self.identity = identity()

    def _event(self, event_id, event_type, obj, created=100):
        return {"id": event_id, "type": event_type, "created": created, "data": {"object": obj}}

    def _register_customer(self):
        self.service.register_user(self.identity)
        self.store.bind_customer(self.identity.user_id, "cus_alpha")

    def test_01_user_without_subscription_has_no_pro(self):
        user = self.service.register_user(self.identity)
        self.assertFalse(entitlement_for(user).has_active_pro)

    def test_02_beta_user_has_access_without_subscription(self):
        beta = Identity(**{**self.identity.__dict__, "beta_access": True})
        self.assertEqual(entitlement_for(self.service.register_user(beta)).reason, "beta_access")

    def test_03_checkout_uses_internal_user_and_existing_customer(self):
        self._register_customer()
        url = self.service.create_checkout_url(self.identity)
        self.assertIn("stripe.test", url)
        self.assertEqual(self.gateway.checkout_calls[0]["user_id"], self.identity.user_id)
        self.assertEqual(self.gateway.checkout_calls[0]["customer_id"], "cus_alpha")

    def test_04_invalid_webhook_signature_is_rejected(self):
        env = {
            "STRIPE_MODE": "test",
            "DATABASE_URL": "postgresql://local/test",
            "STRIPE_SECRET_KEY": "sk_test_placeholder",
            "STRIPE_WEBHOOK_SECRET": "whsec_placeholder",
            "STRIPE_PRICE_PRO_MONTHLY": "price_test_monthly",
            "APP_BASE_URL": "https://beta.example.org",
        }
        with patch.dict(os.environ, env, clear=False):
            with TestClient(app) as client:
                response = client.post(
                    "/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "invalid"}
                )
        self.assertEqual(response.status_code, 400)

    def test_05_checkout_completed_maps_customer_then_syncs_subscription(self):
        self.service.register_user(self.identity)
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity)
        event = self._event(
            "evt_checkout",
            "checkout.session.completed",
            {"client_reference_id": self.identity.user_id, "customer": "cus_alpha", "subscription": "sub_alpha"},
        )
        self.assertTrue(self.service.handle_verified_event(event))
        self.assertEqual(self.store.get_user(self.identity.user_id).stripe_customer_id, "cus_alpha")

    def test_06_active_subscription_grants_pro(self):
        self._register_customer()
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity)
        self.service.handle_verified_event(self._event("evt_active", "customer.subscription.updated", {"id": "sub_alpha"}))
        self.assertTrue(entitlement_for(self.store.get_user(self.identity.user_id)).has_active_pro)

    def test_07_deleted_subscription_ends_pro(self):
        self._register_customer()
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity, status="canceled")
        self.service.handle_verified_event(self._event("evt_deleted", "customer.subscription.deleted", {"id": "sub_alpha"}))
        self.assertFalse(entitlement_for(self.store.get_user(self.identity.user_id)).has_active_pro)

    def test_08_cancel_at_period_end_keeps_active_access(self):
        self._register_customer()
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity, cancel=True)
        self.service.handle_verified_event(self._event("evt_cancel", "customer.subscription.updated", {"id": "sub_alpha"}))
        user = self.store.get_user(self.identity.user_id)
        self.assertTrue(user.cancel_at_period_end)
        self.assertTrue(entitlement_for(user).has_active_pro)

    def test_09_payment_failed_uses_current_subscription_status(self):
        self._register_customer()
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity, status="past_due")
        invoice = {"subscription": "sub_alpha"}
        self.service.handle_verified_event(self._event("evt_failed", "invoice.payment_failed", invoice))
        self.assertEqual(self.store.get_user(self.identity.user_id).subscription_status, "past_due")

    def test_10_duplicate_event_is_ignored(self):
        self._register_customer()
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity)
        event = self._event("evt_duplicate", "customer.subscription.updated", {"id": "sub_alpha"})
        self.assertTrue(self.service.handle_verified_event(event))
        self.assertFalse(self.service.handle_verified_event(event))

    def test_11_older_event_cannot_replace_newer_status(self):
        self._register_customer()
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity, status="canceled")
        self.service.handle_verified_event(
            self._event("evt_new", "customer.subscription.deleted", {"id": "sub_alpha"}, created=200)
        )
        self.gateway.subscriptions["sub_alpha"] = subscription(self.identity, status="active")
        self.service.handle_verified_event(
            self._event("evt_old", "customer.subscription.updated", {"id": "sub_alpha"}, created=100)
        )
        self.assertEqual(self.store.get_user(self.identity.user_id).subscription_status, "canceled")

    def test_12_stripe_outage_does_not_remove_cached_access(self):
        self._register_customer()
        active = BillingUser(
            **{
                **self.store.get_user(self.identity.user_id).__dict__,
                "subscription_status": "active",
                "stripe_subscription_id": "sub_alpha",
            }
        )
        self.store.users[self.identity.user_id] = active
        self.gateway.down = True
        with self.assertRaises(ConnectionError):
            self.service.sync_user(self.identity)
        self.assertTrue(entitlement_for(self.store.get_user(self.identity.user_id)).has_active_pro)

    def test_13_foreign_customer_cannot_be_rebound(self):
        self._register_customer()
        other = identity("beta")
        self.service.register_user(other)
        with self.assertRaises(PermissionError):
            self.store.bind_customer(other.user_id, "cus_alpha")

    def test_14_portal_uses_only_stored_customer(self):
        self._register_customer()
        self.service.create_portal_url(self.identity)
        self.assertEqual(self.gateway.portal_calls[0]["customer_id"], "cus_alpha")

    def test_15_test_and_live_keys_cannot_be_mixed(self):
        self.assertTrue(config(mode="live", key="sk_test_wrong").errors())
        self.assertEqual(config().errors(), [])

    def test_16_logout_clears_billing_redirect_state(self):
        state = {"billing_checkout_url": "https://stripe.test", "billing_return_synced": True, "theme": "dark"}
        clear_sensitive_session(state)
        self.assertNotIn("billing_checkout_url", state)
        self.assertNotIn("billing_return_synced", state)
        self.assertEqual(state["theme"], "dark")


if __name__ == "__main__":
    unittest.main(verbosity=2)
