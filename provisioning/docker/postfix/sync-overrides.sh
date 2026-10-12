#!/usr/bin/env bash
# Applies settings published by the console to Postfix.
#
# The api writes "key = value" files on the runtime volume:
#   postfix-overrides.conf   outbound settings (relayhost, default_transport, hopcount_limit)
#   postfix-plugins.conf     values from enabled plugins (extension point postfix.main)
# This script watches both and, when one changes, applies its allowed keys with postconf and
# reloads Postfix. Each file has its own allow-list and value grammar, so neither can be used to
# set anything else, and plugins can never touch relaying. After applying the plugins file it
# writes the file's SHA-256 to <status>/postfix-plugins.applied so the console can show
# "Applied".
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
SAFE_VALUE='^[][A-Za-z0-9.:_-]*$'
PLUGINS_FILE="${IFINMAIL_PLUGINS_FILE:-/var/lib/ifinmail/runtime/postfix-plugins.conf}"
PLUGINS_STATE="${IFINMAIL_PLUGINS_STATE:-/var/run/ifinmail-plugins.sha256}"
PLUGIN_KEYS=" always_bcc "
PLUGIN_VALUE='^([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)?$'

log() { echo "ifinmail-postfix-sync: $*"; }

# apply_file <file> <state file> <allowed keys> <value regex>; returns 0 when nothing was pending
apply_file() {
    local file="$1" state="$2" allowed="$3" safe="$4"
    [ -r "$file" ] || return 0
    local current previous=""
    current="$(sha256sum "$file" | cut -d' ' -f1)"
    [ -r "$state" ] && previous="$(cat "$state")"
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
        if [[ "$allowed" != *" $key "* ]]; then
            log "ignoring key not on the allow-list: $key"
            continue
        fi
        if [[ ! "$value" =~ $safe ]]; then
            log "ignoring unsafe value for $key"
            continue
        fi
        if [ -z "$value" ]; then
            "$POSTCONF" -X "$key" && changed=1
        else
            "$POSTCONF" -e "$key=$value" && changed=1
        fi
    done < "$file"

    if [ "$changed" = 1 ]; then
        "$POSTFIX" reload >/dev/null 2>&1 || log "postfix reload failed (not running yet?)"
        log "applied $(basename "$file")"
    fi
    echo "$current" > "$state"
}

apply_once() {
    apply_file "$FILE" "$STATE" "$ALLOWED_KEYS" "$SAFE_VALUE"
    apply_file "$PLUGINS_FILE" "$PLUGINS_STATE" "$PLUGIN_KEYS" "$PLUGIN_VALUE"
    acknowledge_plugins
}

# Tell the console which plugins file is in effect (it compares this hash with what it wrote).
acknowledge_plugins() {
    [ -r "$PLUGINS_STATE" ] && [ -d "$STATUS_DIR" ] && [ -w "$STATUS_DIR" ] || return 0
    local applied
    applied="$(cat "$PLUGINS_STATE")"
    [ "$(cat "$STATUS_DIR/postfix-plugins.applied" 2>/dev/null)" = "$applied" ] && return 0
    printf '%s\n' "$applied" > "$STATUS_DIR/postfix-plugins.applied.tmp" \
        && mv "$STATUS_DIR/postfix-plugins.applied.tmp" "$STATUS_DIR/postfix-plugins.applied"
    chmod 644 "$STATUS_DIR/postfix-plugins.applied" 2>/dev/null || true
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
