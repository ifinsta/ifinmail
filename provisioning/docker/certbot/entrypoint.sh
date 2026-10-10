#!/bin/sh
# certbot container entrypoint.
#
#   entrypoint.sh certonly ...   run certbot once with these arguments (used by obtain-ssl.sh)
#   entrypoint.sh                keep one certificate current:
#                                 * renew on a 12h loop
#                                 * every few minutes, re-issue it when the console's list of
#                                   hostnames (cert-hosts.txt) gains a name that resolves here
set -u

if [ "$#" -gt 0 ]; then
    exec certbot "$@"
fi

RENEWAL_INTERVAL="${RENEWAL_INTERVAL:-12h}"
SYNC_INTERVAL="${SYNC_INTERVAL:-300}"
HOSTS_FILE="${HOSTS_FILE:-/runtime/cert-hosts.txt}"
STATE_FILE="${STATE_FILE:-/tmp/cert-hosts.applied}"
WEBROOT="${WEBROOT:-/var/www/certbot}"
MAIL_HOSTNAME="${MAIL_HOSTNAME:?MAIL_HOSTNAME is required}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"

first_ip() { getent hosts "$1" 2>/dev/null | awk 'NR==1 {print $1}'; }

# Names that currently resolve to this server (the mail hostname is always included).
eligible_hosts() {
    server_ip="$(first_ip "$MAIL_HOSTNAME")"
    while IFS= read -r host; do
        [ -n "$host" ] || continue
        if [ "$host" = "$MAIL_HOSTNAME" ]; then
            echo "$host"
            continue
        fi
        ip="$(first_ip "$host")"
        if [ -n "$ip" ] && [ "$ip" = "$server_ip" ]; then
            echo "$host"
        else
            echo "  skipping $host (does not resolve to this server yet)" >&2
        fi
    done < "$HOSTS_FILE"
}

sync_hosts() {
    [ -r "$HOSTS_FILE" ] || return 0
    hosts="$(eligible_hosts)"
    [ -n "$hosts" ] || return 0
    digest="$(printf '%s\n' "$hosts" | sha256sum | cut -d' ' -f1)"
    [ "$digest" = "$(cat "$STATE_FILE" 2>/dev/null)" ] && return 0

    set --
    for host in $hosts; do set -- "$@" -d "$host"; done
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): updating certificate to cover: $hosts"
    email_args="--register-unsafely-without-email"
    [ -n "$ADMIN_EMAIL" ] && email_args="-m $ADMIN_EMAIL"
    # shellcheck disable=SC2086
    if certbot certonly --webroot --webroot-path "$WEBROOT" --cert-name "$MAIL_HOSTNAME" \
        --expand --non-interactive --agree-tos $email_args \
        --deploy-hook "/hooks/deploy-hook.sh" "$@"; then
        echo "$digest" > "$STATE_FILE"
    else
        echo "  certificate update failed; will retry"
    fi
}

echo "=== ifinmail certbot ==="
echo "  Renewal check: every $RENEWAL_INTERVAL; hostname list check: every ${SYNC_INTERVAL}s"

renew_seconds=$(( $(echo "$RENEWAL_INTERVAL" | sed -e 's/h$/*3600/' -e 's/m$/*60/' -e 's/s$//') ))
elapsed=$renew_seconds   # renew straight away on start

while :; do
    sync_hosts
    if [ "$elapsed" -ge "$renew_seconds" ]; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): running certbot renew..."
        certbot renew --deploy-hook "/hooks/deploy-hook.sh" --non-interactive 2>&1 \
            || echo "  Renewal check complete (some failures are expected if certs aren't due yet)."
        elapsed=0
    fi
    sleep "$SYNC_INTERVAL"
    elapsed=$(( elapsed + SYNC_INTERVAL ))
done
