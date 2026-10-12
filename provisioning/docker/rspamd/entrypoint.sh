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

# Plugin settings (rspamd.policy): apply once before Rspamd starts, then watch for changes.
# The first pass must not signal PID 1, which is still this shell.
RSPAMD_RELOAD=true /usr/local/bin/ifinmail-rspamd-sync --once || true
/usr/local/bin/ifinmail-rspamd-sync &

exec rspamd -f -u _rspamd -g _rspamd
