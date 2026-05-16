-- ifinmail database initialization
-- Creates core schema and least-privilege database roles
-- Runs automatically on first PostgreSQL container start

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Domain registry
CREATE TABLE IF NOT EXISTS domains (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    verified BOOLEAN DEFAULT FALSE,
    mx_verified BOOLEAN DEFAULT FALSE,
    spf_verified BOOLEAN DEFAULT FALSE,
    dkim_verified BOOLEAN DEFAULT FALSE,
    dmarc_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User accounts (email address = login)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(512),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(email)
);

-- Virtual mailboxes (one per local_part per domain)
CREATE TABLE IF NOT EXISTS mailboxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    local_part VARCHAR(128) NOT NULL,
    quota_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_id, local_part)
);

-- Email aliases (source → destination forwarding)
CREATE TABLE IF NOT EXISTS aliases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    source VARCHAR(128) NOT NULL,
    destination VARCHAR(255) NOT NULL
);

-- DKIM key registry
CREATE TABLE IF NOT EXISTS dkim_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    selector VARCHAR(64) NOT NULL DEFAULT 'default',
    private_key TEXT NOT NULL,
    public_key TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_id, selector)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_domains_name ON domains(name);
CREATE INDEX IF NOT EXISTS idx_domains_verified ON domains(verified);
CREATE INDEX IF NOT EXISTS idx_mailboxes_lookup ON mailboxes(domain_id, local_part);
CREATE INDEX IF NOT EXISTS idx_aliases_lookup ON aliases(domain_id, source);

-- --- Least-privilege database roles ---

-- Dovecot role: needs SELECT on users for auth
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dovecot') THEN
        CREATE ROLE dovecot WITH LOGIN PASSWORD 'dovecot_password_change_me';
    END IF;
END
$$;
GRANT CONNECT ON DATABASE ifinmail TO dovecot;
GRANT USAGE ON SCHEMA public TO dovecot;
GRANT SELECT ON users TO dovecot;

-- Postfix role: needs SELECT on domains, mailboxes, aliases for virtual lookup
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'postfix') THEN
        CREATE ROLE postfix WITH LOGIN PASSWORD 'postfix_password_change_me';
    END IF;
END
$$;
GRANT CONNECT ON DATABASE ifinmail TO postfix;
GRANT USAGE ON SCHEMA public TO postfix;
GRANT SELECT ON domains TO postfix;
GRANT SELECT ON mailboxes TO postfix;
GRANT SELECT ON aliases TO postfix;
