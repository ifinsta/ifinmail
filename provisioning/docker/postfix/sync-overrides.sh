#!/usr/bin/env bash
# Applies settings published by the console to Postfix.
#
# The api writes "key = value" files on the runtime volume:
#   postfix-overrides.conf   outbound settings (relayhost, default_transport, hopcount_limit)
#   postfix-plugins.conf     values from enabled plugins (extension point postfix.main)
#   postfix-tls-policy.conf  partner domains that must get TLS (extension point postfix.tls_policy),
#                            rendered into a texthash: map used as smtp_tls_policy_maps
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
TLS_FILE="${IFINMAIL_TLS_POLICY_FILE:-/var/lib/ifinmail/runtime/postfix-tls-policy.conf}"
TLS_STATE="${IFINMAIL_TLS_POLICY_STATE:-/var/run/ifinmail-tls-policy.sha256}"
TLS_MAP="${IFINMAIL_TLS_POLICY_MAP:-/etc/postfix/ifinmail_tls_policy}"
DOMAIN='[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+'

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

# Partner TLS: "domains = a.example,b.example" and "level = encrypt|secure" become a texthash:
# map of "domain level" lines. No domains removes the map from Postfix entirely.
apply_tls_policy() {
    [ -r "$TLS_FILE" ] || return 0
    local current previous=""
    current="$(sha256sum "$TLS_FILE" | cut -d' ' -f1)"
    [ -r "$TLS_STATE" ] && previous="$(cat "$TLS_STATE")"
    [ "$current" = "$previous" ] && return 0

    local line key value domains="" level="encrypt"
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^([a-z_]+)[[:space:]]*=[[:space:]]*(.*)$ ]] || { log "ignoring malformed line"; continue; }
        key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
        case "$key" in
            domains)
                if [[ "$value" =~ ^(${DOMAIN}(,${DOMAIN}){0,199})?$ ]]; then domains="$value"
                else log "ignoring unsafe value for domains"; fi ;;
            level)
                if [[ "$value" =~ ^(encrypt|secure)?$ ]]; then level="${value:-encrypt}"
                else log "ignoring unsafe value for level"; fi ;;
            *) log "ignoring key not on the allow-list: $key" ;;
        esac
    done < "$TLS_FILE"

    if [ -z "$domains" ]; then
        "$POSTCONF" -X smtp_tls_policy_maps
        : > "$TLS_MAP"
    else
        local domain
        : > "$TLS_MAP.tmp"
        IFS=',' read -r -a list <<< "$domains"
        for domain in "${list[@]}"; do printf '%s %s\n' "$domain" "$level" >> "$TLS_MAP.tmp"; done
        mv "$TLS_MAP.tmp" "$TLS_MAP"
        "$POSTCONF" -e "smtp_tls_policy_maps=texthash:$TLS_MAP"
    fi
    "$POSTFIX" reload >/dev/null 2>&1 || log "postfix reload failed (not running yet?)"
    log "applied $(basename "$TLS_FILE")"
    echo "$current" > "$TLS_STATE"
}

apply_once() {
    apply_file "$FILE" "$STATE" "$ALLOWED_KEYS" "$SAFE_VALUE"
    apply_file "$PLUGINS_FILE" "$PLUGINS_STATE" "$PLUGIN_KEYS" "$PLUGIN_VALUE"
    apply_tls_policy
    acknowledge "$PLUGINS_STATE" postfix-plugins.applied
    acknowledge "$TLS_STATE" postfix-tls-policy.applied
}

# acknowledge <state file> <ack name>: tell the console which file is in effect.
acknowledge() {
    [ -r "$1" ] && [ -d "$STATUS_DIR" ] && [ -w "$STATUS_DIR" ] || return 0
    local applied
    applied="$(cat "$1")"
    [ "$(cat "$STATUS_DIR/$2" 2>/dev/null)" = "$applied" ] && return 0
    printf '%s\n' "$applied" > "$STATUS_DIR/$2.tmp" && mv "$STATUS_DIR/$2.tmp" "$STATUS_DIR/$2"
    chmod 644 "$STATUS_DIR/$2" 2>/dev/null || true
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
