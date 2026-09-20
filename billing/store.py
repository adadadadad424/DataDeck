"""PostgreSQL persistence for users, subscriptions and webhook idempotency."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import BillingUser, Identity


def _as_user(row: dict[str, Any] | None) -> BillingUser | None:
    return BillingUser(**row) if row else None


class PostgresBillingStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def upsert_identity(self, identity: Identity) -> BillingUser:
        query = """
            INSERT INTO billing_users (
                user_id, email, oidc_issuer, oidc_subject, beta_access, plan
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                email = EXCLUDED.email,
                beta_access = EXCLUDED.beta_access,
                plan = CASE
                    WHEN billing_users.subscription_status IN ('active', 'trialing') THEN 'pro'
                    WHEN EXCLUDED.beta_access THEN 'beta'
                    ELSE 'free'
                END,
                updated_at = NOW()
            RETURNING *
        """
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        identity.user_id,
                        identity.email.casefold(),
                        identity.issuer,
                        identity.subject,
                        identity.beta_access,
                        "beta" if identity.beta_access else "free",
                    ),
                )
                return _as_user(cursor.fetchone())  # type: ignore[return-value]

    def get_user(self, user_id: str) -> BillingUser | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM billing_users WHERE user_id = %s", (user_id,))
                return _as_user(cursor.fetchone())

    def bind_customer(self, user_id: str, customer_id: str) -> BillingUser:
        """Bind once; a user can never replace another user's customer ID."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE billing_users
                    SET stripe_customer_id = %s, updated_at = NOW()
                    WHERE user_id = %s
                      AND (stripe_customer_id IS NULL OR stripe_customer_id = %s)
                    RETURNING *
                    """,
                    (customer_id, user_id, customer_id),
                )
                user = _as_user(cursor.fetchone())
                if user is None:
                    raise PermissionError("Stripe customer does not belong to this user")
                return user

    def update_subscription_snapshot(
        self,
        *,
        user_id: str,
        customer_id: str,
        subscription_id: str,
        status: str,
        current_period_end: dt.datetime | None,
        cancel_at_period_end: bool,
    ) -> BillingUser:
        plan = "pro" if status in {"active", "trialing"} else "free"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE billing_users
                    SET stripe_subscription_id = %s,
                        subscription_status = %s,
                        current_period_end = %s,
                        cancel_at_period_end = %s,
                        plan = CASE WHEN %s = 'pro' THEN 'pro'
                                    WHEN beta_access THEN 'beta' ELSE 'free' END,
                        last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE user_id = %s AND stripe_customer_id = %s
                    RETURNING *
                    """,
                    (
                        subscription_id,
                        status,
                        current_period_end,
                        cancel_at_period_end,
                        plan,
                        user_id,
                        customer_id,
                    ),
                )
                user = _as_user(cursor.fetchone())
                if user is None:
                    raise PermissionError("Stripe customer does not belong to this user")
                return user

    def process_event_once(
        self,
        event_id: str,
        event_type: str,
        event_created: int,
        mutation: Callable[[psycopg.Connection], None],
    ) -> bool:
        """Insert and mutate in one transaction; rollback leaves the event retryable."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO stripe_events (event_id, event_type, event_created)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (event_id, event_type, event_created),
                )
                if cursor.rowcount == 0:
                    return False
                mutation(connection)
        return True

    @staticmethod
    def bind_customer_in_transaction(
        connection: psycopg.Connection,
        user_id: str,
        customer_id: str,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE billing_users
                SET stripe_customer_id = %s, updated_at = NOW()
                WHERE user_id = %s
                  AND (stripe_customer_id IS NULL OR stripe_customer_id = %s)
                """,
                (customer_id, user_id, customer_id),
            )
            if cursor.rowcount != 1:
                raise PermissionError("Invalid Stripe customer mapping")

    @staticmethod
    def apply_subscription_in_transaction(
        connection: psycopg.Connection,
        *,
        user_id: str,
        customer_id: str,
        subscription_id: str,
        status: str,
        current_period_end: dt.datetime | None,
        cancel_at_period_end: bool,
        event_created: int,
    ) -> None:
        plan = "pro" if status in {"active", "trialing"} else "free"
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE billing_users
                SET stripe_customer_id = %s,
                    stripe_subscription_id = %s,
                    subscription_status = %s,
                    current_period_end = %s,
                    cancel_at_period_end = %s,
                    plan = CASE WHEN %s = 'pro' THEN 'pro'
                                WHEN beta_access THEN 'beta' ELSE 'free' END,
                    last_stripe_event_created = %s,
                    last_synced_at = NOW(),
                    updated_at = NOW()
                WHERE user_id = %s
                  AND (stripe_customer_id IS NULL OR stripe_customer_id = %s)
                  AND last_stripe_event_created <= %s
                """,
                (
                    customer_id,
                    subscription_id,
                    status,
                    current_period_end,
                    cancel_at_period_end,
                    plan,
                    event_created,
                    user_id,
                    customer_id,
                    event_created,
                ),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT last_stripe_event_created FROM billing_users WHERE user_id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise LookupError("Unknown DataDeck user")
                if int(row["last_stripe_event_created"]) <= event_created:
                    raise PermissionError("Stripe customer belongs to another user")
