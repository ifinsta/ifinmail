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

# The console's IMAP master login (see conf.d/10-auth.conf). Hashed here; allowed only from
# private networks. Without DOVECOT_MASTER_PASSWORD the file is empty: no master login exists.
: > /etc/dovecot/master-users
if [ -n "${DOVECOT_MASTER_PASSWORD:-}" ]; then
    MASTER_HASH="$(doveadm pw -s SHA512-CRYPT -p "$DOVECOT_MASTER_PASSWORD")"
    printf 'ifinmail-console:%s::::::allow_nets=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16\n' \
        "$MASTER_HASH" > /etc/dovecot/master-users
fi
chown root:dovecot /etc/dovecot/master-users
chmod 640 /etc/dovecot/master-users

# The mail volume is shared with the postfix container, and whichever container
# starts first initialises it from its own image (root:mail 2755 from postfix).
# Dovecot delivers as vmail, which then could not create <domain>/<user>/ and
# every LMTP delivery failed with "451 4.2.0 Internal error".
chown vmail:vmail /var/mail/vhosts
chmod 0755 /var/mail/vhosts

# Certificates come from the whole Let's Encrypt tree (live/ files link into archive/).
ln -sfn "/etc/letsencrypt/live/${MAIL_HOSTNAME:?MAIL_HOSTNAME is required}" /etc/dovecot/certs

# The log is a file on a volume the console reads (the threat digest counts failed sign-ins);
# tail forwards it to the container output so docker logs shows the same lines. Without the
# volume the default in dovecot.conf (the container output) stays in force.
MAIL_LOG=/var/log/ifinmail/dovecot.log
if mkdir -p "$(dirname "$MAIL_LOG")" 2>/dev/null && touch "$MAIL_LOG" 2>/dev/null; then
    chmod 0644 "$MAIL_LOG"
    printf 'log_path = %s\n' "$MAIL_LOG" > /etc/dovecot/ifinmail-log.conf
    tail -n 0 -F "$MAIL_LOG" &
    /usr/local/bin/ifinmail-log-rotate "$MAIL_LOG" &
fi

# Plugin settings (dovecot.policy): apply once before Dovecot starts, then watch for changes.
DOVECOT_RELOAD=true /usr/local/bin/ifinmail-dovecot-sync --once || true
/usr/local/bin/ifinmail-dovecot-sync &

exec "$@"
