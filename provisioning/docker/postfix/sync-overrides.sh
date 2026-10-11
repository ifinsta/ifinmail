#!/usr/bin/env bash
# Applies the outbound-mail settings published by the console to Postfix.
#
# The api writes <runtime>/postfix-overrides.conf ("key = value" lines). This
# script watches it and, when it changes, applies the allowed keys with postconf
# and reloads Postfix. Only the keys below are ever applied, and values must look
# like hostnames/numbers, so the file cannot be used to inject other settings.
#
#   ifinmail-postfix-sync          run forever (default interval 10s)
#   ifinmail-postfix-sync --once   apply once and exit (used by tests)
set -u

FILE="${IFINMAIL_OVERRIDES_FILE:-/var/lib/ifinmail/runtime/postfix-overrides.conf}"
STATE="${IFINMAIL_OVERRIDES_STATE:-/var/run/ifinmail-overrides.sha256}"
INTERVAL="${IFINMAIL_SYNC_INTERVAL:-10}"
POSTCONF="${POSTCONF_BIN:-postconf}"
POSTFIX="${POSTFIX_BIN:-postfix}"
ALLOWED_KEYS=" relayhost default_transport hopcount_limit "

log() { echo "ifinmail-postfix-sync: $*"; }

apply_once() {
    [ -r "$FILE" ] || return 0
    local current previous=""
    current="$(sha256sum "$FILE" | cut -d' ' -f1)"
    [ -r "$STATE" ] && previous="$(cat "$STATE")"
    [ "$current" = "$previous" ] && return 0

    local line key value changed=0
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ ! "$line" =~ ^([a-z_]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            log "ignoring malformed line"
            continue
        fi
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        if [[ "$ALLOWED_KEYS" != *" $key "* ]]; then
            log "ignoring key not on the allow-list: $key"
            continue
        fi
        if [[ ! "$value" =~ ^[][A-Za-z0-9.:_-]*$ ]]; then
            log "ignoring unsafe value for $key"
            continue
        fi
        if [ -z "$value" ]; then
            "$POSTCONF" -X "$key" && changed=1
        else
            "$POSTCONF" -e "$key=$value" && changed=1
        fi
    done < "$FILE"

    if [ "$changed" = 1 ]; then
        "$POSTFIX" reload >/dev/null 2>&1 || log "postfix reload failed (not running yet?)"
        log "applied $(basename "$FILE")"
    fi
    echo "$current" > "$STATE"
}

# Queue counts for the console's System health page (it cannot see Postfix's spool).
STATUS_DIR="${IFINMAIL_STATUS_DIR:-/var/lib/ifinmail/status}"
QUEUE_EVERY="${IFINMAIL_QUEUE_EVERY:-6}"   # loops between publications (6 x 10s = 1 min)

publish_queue() {
    [ -d "$STATUS_DIR" ] && [ -w "$STATUS_DIR" ] || return 0
    local now
    now="$(date +%s)"
    # postqueue -j prints one JSON object per message: count by queue, and note the oldest
    # deferred message, without needing a JSON tool in the image.
    postqueue -j 2>/dev/null | awk -v now="$now" '
        {
            q = $0; sub(/.*"queue_name": *"/, "", q); sub(/".*/, "", q)
            t = $0; sub(/.*"arrival_time": */, "", t); sub(/[^0-9].*/, "", t)
            count[q]++
            if (q == "deferred" && t != "" && (oldest == "" || t + 0 < oldest + 0)) oldest = t
        }
        END {
            age = (oldest == "") ? 0 : now - oldest
            printf "{\"updated\": %d, \"active\": %d, \"deferred\": %d, \"hold\": %d, \"incoming\": %d, \"oldest_deferred_seconds\": %d}\n", now, count["active"], count["deferred"], count["hold"], count["incoming"], age
        }' > "$STATUS_DIR/mailq.json.tmp" && mv "$STATUS_DIR/mailq.json.tmp" "$STATUS_DIR/mailq.json"
    chmod 644 "$STATUS_DIR/mailq.json" 2>/dev/null || true
}

if [ "${1:-}" = "--once" ]; then
    apply_once
    exit 0
fi

loops=0
while :; do
    apply_once
    if [ $((loops % QUEUE_EVERY)) -eq 0 ]; then
        publish_queue
    fi
    loops=$((loops + 1))
    sleep "$INTERVAL"
done
