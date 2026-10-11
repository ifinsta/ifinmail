-- Idempotent grants applied on every provision (safe to re-run).
-- init-db.sh only runs when the database is first created, so installs that
-- predate a grant get it here.

-- domains.ip_address is mapped by the Domain model (the migration for it is state-only).
ALTER TABLE domains ADD COLUMN IF NOT EXISTS ip_address INET;

-- MailUser.role_id is mapped by migration accounts.0003 (state-only: the users
-- table is owned by init-db.sh). Plain UUID, no REFERENCES: SET_NULL on role
-- delete is applied by the Django ORM.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id UUID;

-- Dovecot reads the mailbox quota to enforce it at login and delivery.
GRANT SELECT ON domains TO dovecot;
GRANT SELECT ON mailboxes TO dovecot;

-- Django migrations (admin log, axes) add foreign keys to users; that needs REFERENCES.
-- Without it the api's first `migrate` fails and the container never becomes healthy.
GRANT REFERENCES ON ALL TABLES IN SCHEMA public TO ifinmail_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT REFERENCES ON TABLES TO ifinmail_app;
