CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE billing_users (
    user_id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    oidc_issuer TEXT NOT NULL,
    oidc_subject TEXT NOT NULL,
    beta_access BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'beta', 'pro')),
    subscription_status TEXT CHECK (
        subscription_status IS NULL OR subscription_status IN (
            'active', 'trialing', 'past_due', 'canceled', 'unpaid',
            'incomplete', 'incomplete_expired', 'paused'
        )
    ),
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    last_stripe_event_created BIGINT NOT NULL DEFAULT 0,
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (oidc_issuer, oidc_subject)
);

CREATE TABLE stripe_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_created BIGINT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX billing_users_customer_idx ON billing_users (stripe_customer_id);
CREATE INDEX billing_users_subscription_idx ON billing_users (stripe_subscription_id);
