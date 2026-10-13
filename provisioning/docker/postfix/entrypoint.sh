#!/usr/bin/env bash
set -eu

sed_escape() {
    printf "%s" "$1" | sed 's/[|&]/\\&/g'
}

: "${MAIL_HOSTNAME:?MAIL_HOSTNAME is required}"
: "${MAIL_DOMAIN:?MAIL_DOMAIN is required}"
POSTFIX_DB_PASSWORD="${POSTFIX_DB_PASSWORD:?POSTFIX_DB_PASSWORD is required}"

MAIL_HOSTNAME_ESC="$(sed_escape "$MAIL_HOSTNAME")"
MAIL_DOMAIN_ESC="$(sed_escape "$MAIL_DOMAIN")"
POSTFIX_DB_PASSWORD_ESC="$(sed_escape "$POSTFIX_DB_PASSWORD")"

sed \
    -e "s|__MAIL_HOSTNAME__|$MAIL_HOSTNAME_ESC|g" \
    -e "s|__MAIL_DOMAIN__|$MAIL_DOMAIN_ESC|g" \
    /etc/postfix/main.cf.template > /etc/postfix/main.cf

for template in /etc/postfix/pgsql-templates/*.cf; do
    map="/etc/postfix/pgsql/$(basename "$template")"
    sed "s|__POSTFIX_DB_PASSWORD__|$POSTFIX_DB_PASSWORD_ESC|g" "$template" > "$map"
    chown root:postfix "$map"
    chmod 640 "$map"
done

# Certificates are read straight from the Let's Encrypt tree (main.cf names
# /etc/letsencrypt/live/<host>/); an old /etc/postfix/certs symlink only made
# postfix-script warn "symlink leaves directory" on every start.
if [ -L /etc/postfix/certs ]; then rm -f /etc/postfix/certs; fi

# No chroot: the Debian default runs trivial-rewrite, cleanup and others inside
# /var/spool/postfix, where Docker's resolver and /etc/hosts are absent, so the
# "postgres" host never resolved and every recipient got "451 4.3.0 Temporary
# lookup failure". The container already isolates Postfix.
postconf -F '*/*/chroot = n'

# The internal relay (master.cf, port 10025) accepts mail only from the ifinmail Docker
# network, whose subnet Docker picks. No route found = the main.cf default (localhost only).
internal_net="$(ip -4 route show scope link 2>/dev/null | awk '$1 ~ /\// {print $1; exit}')"
if [ -n "$internal_net" ]; then
    postconf -P "10025/inet/mynetworks=127.0.0.0/8,$internal_net"
fi

# Log to the container output (docker logs): without a syslog daemon Postfix
# logged nowhere. postlogd needs its own service entry.
postconf -Me 'postlog/unix-dgram=postlog unix-dgram n - n - 1 postlogd'
# The log is a file on a volume the console reads (the threat digest counts failed sign-ins and
# relay attempts); tail forwards it to the container output so docker logs shows the same lines.
# Without the volume Postfix logs straight to the container output as before.
MAIL_LOG=/var/log/ifinmail/postfix.log
if mkdir -p "$(dirname "$MAIL_LOG")" 2>/dev/null && touch "$MAIL_LOG" 2>/dev/null; then
    chmod 0644 "$MAIL_LOG"
    postconf -e "maillog_file=$MAIL_LOG"
    tail -n 0 -F "$MAIL_LOG" &
    /usr/local/bin/ifinmail-log-rotate "$MAIL_LOG" &
else
    postconf -e maillog_file=/dev/stdout
fi

mkdir -p /var/spool/postfix /var/mail/vhosts
if command -v postfix >/dev/null 2>&1; then
    postfix set-permissions >/dev/null 2>&1 || true
fi
for root_owned_dir in \
    /var/spool/postfix/etc \
    /var/spool/postfix/lib \
    /var/spool/postfix/usr \
    /var/spool/postfix/usr/lib \
    /var/spool/postfix/usr/lib/sasl2 \
    /var/spool/postfix/usr/lib/zoneinfo
do
    [ -d "$root_owned_dir" ] && chown root:root "$root_owned_dir"
done

# Wait for PostgreSQL to accept connections
echo "Waiting for PostgreSQL readiness..."
for i in $(seq 1 30); do
    if timeout 3 bash -c "echo > /dev/tcp/postgres/5432" 2>/dev/null; then
        echo "PostgreSQL is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: PostgreSQL not ready after 30 attempts. Starting anyway..."
    else
        sleep 2
    fi
done

# Apply outbound settings published by the console (relay, proxy, hop limit).
if [ -x /usr/local/bin/ifinmail-postfix-sync ]; then
    /usr/local/bin/ifinmail-postfix-sync &
fi

exec "$@"
