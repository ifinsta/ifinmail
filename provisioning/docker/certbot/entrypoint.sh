#!/bin/sh
# certbot container entrypoint.
#
#   entrypoint.sh certonly ...   run certbot once with these arguments (used by obtain-ssl.sh)
#   entrypoint.sh                keep one certificate current:
#                                 * renew on a 12h loop
#                                 * every few minutes, re-issue it when the console's list of
#                                   hostnames (cert-hosts.txt) gains a name that resolves here
#                                 * every few seconds, act on a request from the console
#                                   (cert-request.json): issue, renew, install an uploaded
#                                   certificate, or go back to Let's Encrypt; the outcome is
#                                   written to cert-status.json and the mode to tls-mode
set -u

if [ "$#" -gt 0 ]; then
    exec certbot "$@"
fi

RENEWAL_INTERVAL="${RENEWAL_INTERVAL:-12h}"
SYNC_INTERVAL="${SYNC_INTERVAL:-300}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
RUNTIME="${RUNTIME:-/runtime}"
HOSTS_FILE="${HOSTS_FILE:-$RUNTIME/cert-hosts.txt}"
REQUEST_FILE="$RUNTIME/cert-request.json"
STATUS_FILE="$RUNTIME/cert-status.json"
MODE_FILE="$RUNTIME/tls-mode"
INCOMING="$RUNTIME/tls/incoming"
CERTS="${CERTS:-/etc/letsencrypt}"
HANDLED_FILE="${HANDLED_FILE:-/tmp/cert-request.handled}"
LAST_MSG="${LAST_MSG:-/tmp/cert-last.msg}"
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
        --deploy-hook "/hooks/deploy-hook.sh" "$@" > "$LAST_MSG" 2>&1; then
        echo "$digest" > "$STATE_FILE"
        return 0
    else
        tail -n 5 "$LAST_MSG"
        echo "  certificate update failed; will retry"
        return 1
    fi
}

tls_mode() { cat "$MODE_FILE" 2>/dev/null || echo letsencrypt; }

atomic_write() { # file content
    printf '%s\n' "$2" > "$1.tmp" && mv "$1.tmp" "$1"
}

write_status() { # request_id action ok message
    msg="$(printf '%s' "$4" | tr '\n"\\' '  /' | cut -c1-400)"
    atomic_write "$STATUS_FILE" "$(printf '{"updated":"%s","request_id":"%s","action":"%s","ok":%s,"message":"%s"}' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$msg")"
}

last_lines() { tail -n 3 "$LAST_MSG" 2>/dev/null | tr '\n' ' '; }

install_custom() {
    live="$CERTS/live/$MAIL_HOSTNAME"
    keep="$CERTS/custom/$MAIL_HOSTNAME"
    if [ -s "$INCOMING/fullchain.pem" ] && [ -s "$INCOMING/privkey.pem" ]; then
        mkdir -p "$keep" && chmod 700 "$keep"
        mv "$INCOMING/fullchain.pem" "$keep/fullchain.pem"
        mv "$INCOMING/privkey.pem" "$keep/privkey.pem"
        chmod 600 "$keep/privkey.pem"
    fi
    [ -s "$keep/fullchain.pem" ] && [ -s "$keep/privkey.pem" ] || { echo "no uploaded certificate"; return 1; }
    cert_pub="$(openssl x509 -in "$keep/fullchain.pem" -noout -pubkey 2>/dev/null | sha256sum)"
    key_pub="$(openssl pkey -in "$keep/privkey.pem" -pubout 2>/dev/null | sha256sum)"
    [ "$cert_pub" = "$key_pub" ] || { echo "the private key does not match the certificate"; return 1; }
    rm -rf "$live" && mkdir -p "$live"
    cp "$keep/fullchain.pem" "$live/fullchain.pem"
    cp "$keep/privkey.pem" "$live/privkey.pem"
    cp "$keep/fullchain.pem" "$live/cert.pem"
    chmod 644 "$live/fullchain.pem" "$live/cert.pem"; chmod 640 "$live/privkey.pem"
    atomic_write "$MODE_FILE" custom
    /hooks/deploy-hook.sh >/dev/null 2>&1 || echo "  could not restart services; run 'make reload'"
    return 0
}

use_letsencrypt() {
    live="$CERTS/live/$MAIL_HOSTNAME"
    rm -rf "$live" "$CERTS/archive/$MAIL_HOSTNAME" "$CERTS/renewal/$MAIL_HOSTNAME.conf"
    rm -f "$STATE_FILE"
    atomic_write "$MODE_FILE" letsencrypt
    if sync_hosts; then
        return 0
    fi
    echo "Let's Encrypt failed: $(last_lines)" > "$LAST_MSG.reason"
    install_custom >/dev/null 2>&1   # put the uploaded certificate back; the site must keep working
    return 1
}

handle_request() {
    [ -r "$REQUEST_FILE" ] || return 0
    req_id="$(jq -r '.id // empty' "$REQUEST_FILE" 2>/dev/null)"
    action="$(jq -r '.action // empty' "$REQUEST_FILE" 2>/dev/null)"
    [ -n "$req_id" ] || return 0
    [ "$req_id" = "$(cat "$HANDLED_FILE" 2>/dev/null)" ] && return 0
    echo "$req_id" > "$HANDLED_FILE"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): console request: $action"
    : > "$LAST_MSG"
    case "$action" in
        issue)
            if [ "$(tls_mode)" = custom ]; then
                write_status "$req_id" "$action" false "An uploaded certificate is in use. Switch back to Let's Encrypt first."
            elif [ ! -r "$HOSTS_FILE" ]; then
                write_status "$req_id" "$action" false "The console has not published the hostname list yet."
            else
                rm -f "$STATE_FILE"
                if sync_hosts; then write_status "$req_id" "$action" true "Certificate issued and services reloaded."
                else write_status "$req_id" "$action" false "Issuance failed: $(last_lines)"; fi
            fi ;;
        renew)
            if [ "$(tls_mode)" = custom ]; then
                write_status "$req_id" "$action" false "An uploaded certificate is in use; it is not renewed automatically."
            elif certbot renew --force-renewal --deploy-hook "/hooks/deploy-hook.sh" --non-interactive > "$LAST_MSG" 2>&1; then
                write_status "$req_id" "$action" true "Certificate renewed and services reloaded."
            else write_status "$req_id" "$action" false "Renewal failed: $(last_lines)"; fi ;;
        custom)
            if msg="$(install_custom)"; then write_status "$req_id" "$action" true "Uploaded certificate installed and services reloaded."
            else write_status "$req_id" "$action" false "Not installed: $msg"; fi ;;
        letsencrypt)
            if use_letsencrypt; then write_status "$req_id" "$action" true "Now using a Let's Encrypt certificate."
            else write_status "$req_id" "$action" false "$(cat "$LAST_MSG.reason" 2>/dev/null) The uploaded certificate was kept."; fi ;;
        *) write_status "$req_id" "$action" false "Unknown request." ;;
    esac
}

echo "=== ifinmail certbot ==="
echo "  Renewal check: every $RENEWAL_INTERVAL; hostname list: every ${SYNC_INTERVAL}s; console requests: every ${POLL_INTERVAL}s"

renew_seconds=$(( $(echo "$RENEWAL_INTERVAL" | sed -e 's/h$/*3600/' -e 's/m$/*60/' -e 's/s$//') ))
elapsed=$renew_seconds     # renew straight away on start
since_sync=$SYNC_INTERVAL  # and look at the hostname list straight away

while :; do
    handle_request
    if [ "$(tls_mode)" != custom ]; then
        if [ "$since_sync" -ge "$SYNC_INTERVAL" ]; then
            sync_hosts
            since_sync=0
        fi
        if [ "$elapsed" -ge "$renew_seconds" ]; then
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): running certbot renew..."
            certbot renew --deploy-hook "/hooks/deploy-hook.sh" --non-interactive 2>&1 \
                || echo "  Renewal check complete (some failures are expected if certs aren't due yet)."
            elapsed=0
        fi
    fi
    sleep "$POLL_INTERVAL"
    elapsed=$(( elapsed + POLL_INTERVAL ))
    since_sync=$(( since_sync + POLL_INTERVAL ))
done
