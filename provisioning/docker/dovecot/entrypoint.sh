#!/usr/bin/env sh
set -eu

sed_escape() {
    printf "%s" "$1" | sed 's/[|&]/\\&/g'
}

DOVECOT_DB_PASSWORD="${DOVECOT_DB_PASSWORD:?DOVECOT_DB_PASSWORD is required}"
PGSSLMODE="${PGSSLMODE:-prefer}"

DOVECOT_DB_PASSWORD_ESC="$(sed_escape "$DOVECOT_DB_PASSWORD")"
PGSSLMODE_ESC="$(sed_escape "$PGSSLMODE")"
sed \
    -e "s|__DOVECOT_DB_PASSWORD__|$DOVECOT_DB_PASSWORD_ESC|g" \
    -e "s|__PGSSLMODE__|$PGSSLMODE_ESC|g" \
    /etc/dovecot/dovecot-sql.conf.ext.template > /etc/dovecot/dovecot-sql.conf.ext
chown root:dovecot /etc/dovecot/dovecot-sql.conf.ext
chmod 640 /etc/dovecot/dovecot-sql.conf.ext

# The mail volume is shared with the postfix container, and whichever container
# starts first initialises it from its own image (root:mail 2755 from postfix).
# Dovecot delivers as vmail, which then could not create <domain>/<user>/ and
# every LMTP delivery failed with "451 4.2.0 Internal error".
chown vmail:vmail /var/mail/vhosts
chmod 0755 /var/mail/vhosts

# Certificates come from the whole Let's Encrypt tree (live/ files link into archive/).
ln -sfn "/etc/letsencrypt/live/${MAIL_HOSTNAME:?MAIL_HOSTNAME is required}" /etc/dovecot/certs

exec "$@"
