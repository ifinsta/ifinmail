#!/usr/bin/env bash
set -euo pipefail

sql_escape() {
    printf "%s" "$1" | sed "s/'/''/g"
}

DOVECOT_PASSWORD="$(sql_escape "${DOVECOT_DB_PASSWORD:?DOVECOT_DB_PASSWORD is required}")"
POSTFIX_PASSWORD="$(sql_escape "${POSTFIX_DB_PASSWORD:?POSTFIX_DB_PASSWORD is required}")"
MAIL_DOMAIN_VALUE="$(sql_escape "${MAIL_DOMAIN:-${DOMAIN:-ifinsta.online}}")"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

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

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(512),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(email)
);

CREATE TABLE IF NOT EXISTS mailboxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    local_part VARCHAR(128) NOT NULL,
    quota_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_id, local_part)
);

CREATE TABLE IF NOT EXISTS aliases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    source VARCHAR(128) NOT NULL,
    destination VARCHAR(255) NOT NULL
);

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

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_domains_name ON domains(name);
CREATE INDEX IF NOT EXISTS idx_domains_verified ON domains(verified);
CREATE INDEX IF NOT EXISTS idx_mailboxes_lookup ON mailboxes(domain_id, local_part);
CREATE INDEX IF NOT EXISTS idx_aliases_lookup ON aliases(domain_id, source);

DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dovecot') THEN
        CREATE ROLE dovecot WITH LOGIN PASSWORD '$DOVECOT_PASSWORD';
    ELSE
        ALTER ROLE dovecot WITH LOGIN PASSWORD '$DOVECOT_PASSWORD';
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'postfix') THEN
        CREATE ROLE postfix WITH LOGIN PASSWORD '$POSTFIX_PASSWORD';
    ELSE
        ALTER ROLE postfix WITH LOGIN PASSWORD '$POSTFIX_PASSWORD';
    END IF;
END
\$\$;

GRANT CONNECT ON DATABASE ifinmail TO dovecot;
GRANT USAGE ON SCHEMA public TO dovecot;
GRANT SELECT ON users TO dovecot;

GRANT CONNECT ON DATABASE ifinmail TO postfix;
GRANT USAGE ON SCHEMA public TO postfix;
GRANT SELECT ON domains TO postfix;
GRANT SELECT ON mailboxes TO postfix;
GRANT SELECT ON aliases TO postfix;

INSERT INTO domains (name, verified, mx_verified, spf_verified, dkim_verified, dmarc_verified)
VALUES ('$MAIL_DOMAIN_VALUE', TRUE, FALSE, FALSE, FALSE, FALSE)
ON CONFLICT (name) DO NOTHING;
SQL
