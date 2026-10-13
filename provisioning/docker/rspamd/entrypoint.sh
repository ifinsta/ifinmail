#!/bin/sh
set -e

# Set rspamd controller password if provided
if [ -n "${RSPAMD_CONTROLLER_PASSWORD:-}" ]; then
    HASH="$(rspamadm pw --password "$RSPAMD_CONTROLLER_PASSWORD" 2>/dev/null || echo "")"
    if [ -n "$HASH" ]; then
        sed "s|password = .*|password = \"$HASH\";|" \
            /etc/rspamd/local.d/worker-controller.inc > /tmp/worker-controller.inc
        mv /tmp/worker-controller.inc /etc/rspamd/local.d/worker-controller.inc
        echo "Rspamd controller password configured."
    fi
fi

# Configure Redis password if provided
if [ -n "${REDIS_PASSWORD:-}" ]; then
    REDIS_ESC="$(printf '%s' "$REDIS_PASSWORD" | sed 's/[&/\]/\\&/g')"
    sed "s|password = \"__REDIS_PASSWORD__\";|password = \"$REDIS_ESC\";|" \
        /etc/rspamd/local.d/redis.conf > /tmp/redis.conf
    mv /tmp/redis.conf /etc/rspamd/local.d/redis.conf
    echo "Rspamd Redis password configured."
fi

# The log lives on a volume the console reads; tail forwards it to docker logs, and the
# rotation script keeps it from growing without bound (see log-rotate.sh).
MAIL_LOG=/var/log/ifinmail/rspamd.log
mkdir -p "$(dirname "$MAIL_LOG")"
touch "$MAIL_LOG" && chown _rspamd:_rspamd "$MAIL_LOG" && chmod 0644 "$MAIL_LOG"
tail -n 0 -F "$MAIL_LOG" &
/usr/local/bin/ifinmail-log-rotate "$MAIL_LOG" &

# Plugin settings (rspamd.policy): apply once before Rspamd starts, then watch for changes.
# The first pass must not signal PID 1, which is still this shell.
RSPAMD_RELOAD=true /usr/local/bin/ifinmail-rspamd-sync --once || true
/usr/local/bin/ifinmail-rspamd-sync &

exec rspamd -f -u _rspamd -g _rspamd
