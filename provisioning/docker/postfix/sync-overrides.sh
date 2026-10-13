#!/usr/bin/env bash
# Applies settings published by the console to Postfix.
#
# The api writes "key = value" files on the runtime volume:
#   postfix-overrides.conf   outbound settings (relayhost, default_transport, hopcount_limit)
#   postfix-plugins.conf     values from enabled plugins (extension point postfix.main)
#   postfix-tls-policy.conf  partner domains that must get TLS (extension point postfix.tls_policy),
#                            rendered into a texthash: map used as smtp_tls_policy_maps
#   postfix-sender-policy.conf  who may send where: internal-only logins, paused logins and blocked
#                            destinations (extension point postfix.sender_policy), put in front of
#                            ifinmail_submission_restrictions
# A plugin value that is removed restores the value in main.cf.template, never Postfix's own
# default (e.g. message_size_limit would otherwise drop from this server's 50 MB to 10 MB).
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
PLUGIN_KEYS=" always_bcc message_size_limit_mb recipient_limit "
declare -A PLUGIN_RULES=(
    [always_bcc]='^([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)?$'
    [message_size_limit_mb]='^([1-9]|[1-4][0-9]|50)?$'
    [recipient_limit]='^([1-9][0-9]{0,2}|1000)?$'
)
TEMPLATE="${IFINMAIL_MAIN_CF_TEMPLATE:-/etc/postfix/main.cf.template}"
SENDER_FILE="${IFINMAIL_SENDER_POLICY_FILE:-/var/lib/ifinmail/runtime/postfix-sender-policy.conf}"
SENDER_STATE="${IFINMAIL_SENDER_POLICY_STATE:-/var/run/ifinmail-sender-policy.sha256}"
SENDER_MAP="${IFINMAIL_SENDER_POLICY_MAP:-/etc/postfix/ifinmail_internal_only}"
DEST_MAP="${IFINMAIL_BLOCKED_DESTINATIONS_MAP:-/etc/postfix/ifinmail_blocked_destinations}"
SUBMISSION_DEFAULT='permit_sasl_authenticated, reject'
TLS_FILE="${IFINMAIL_TLS_POLICY_FILE:-/var/lib/ifinmail/runtime/postfix-tls-policy.conf}"
TLS_STATE="${IFINMAIL_TLS_POLICY_STATE:-/var/run/ifinmail-tls-policy.sha256}"
TLS_MAP="${IFINMAIL_TLS_POLICY_MAP:-/etc/postfix/ifinmail_tls_policy}"
DOMAIN='[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+'
CERT_FILE="${IFINMAIL_CERT_FILE:-/etc/letsencrypt/live/${MAIL_HOSTNAME:-}/fullchain.pem}"
CERT_SEEN=''

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
        local re="$safe"
        [ "$safe" = per-key ] && re="${PLUGIN_RULES[$key]}"
        if [[ ! "$value" =~ $re ]]; then
            log "ignoring unsafe value for $key"
            continue
        fi
        if [ "$key" = message_size_limit_mb ]; then
            key=message_size_limit
            [ -n "$value" ] && value=$((value * 1048576))
        fi
        # master.cf passes this to the submission services only (port 25 keeps Postfix's limit).
        [ "$key" = recipient_limit ] && key=ifinmail_recipient_limit
        if [ -z "$value" ]; then
            restore_default "$key" && changed=1
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

# restore_default <key>: back to this server's main.cf value, or Postfix's default if it has none.
restore_default() {
    local value
    value="$(sed -n "s/^$1[[:space:]]*=[[:space:]]*//p" "$TEMPLATE" 2>/dev/null | tr -d '\r' | tail -1)"
    if [ -n "$value" ]; then "$POSTCONF" -e "$1=$value"; else "$POSTCONF" -X "$1"; fi
}

# valid_list <value> <item regex> <max items>: empty, or comma-separated items that each match.
# One regex per item instead of one huge repeated pattern, which bash compiles very slowly.
valid_list() {
    [ -z "$1" ] && return 0
    [[ "$1" =~ ^,|,$|,, ]] && return 1
    local -a items=()
    IFS=',' read -r -a items <<< "$1"
    [ "${#items[@]}" -le "$3" ] || return 1
    local item
    for item in "${items[@]}"; do [[ "$item" =~ ^($2)$ ]] || return 1; done
    return 0
}

# Who may send where, for authenticated submission (extension point postfix.sender_policy):
#   internal_only_logins  a@x,b@x  may send only to domains hosted here (class in main.cf)
#   paused_logins         a@x      may not send at all (containment of a suspected compromise)
#   blocked_destinations  d.test,u@d.test  nobody may send to these (subdomains included)
# They become two texthash: maps and one parameter, ifinmail_submission_restrictions, that both
# submission services in master.cf use. The destination check comes first because a class that
# permits local delivery would otherwise end the checks early. The complete value is always
# written (never removed), so clearing every list restores the default.
apply_sender_policy() {
    [ -r "$SENDER_FILE" ] || return 0
    local current previous=""
    current="$(sha256sum "$SENDER_FILE" | cut -d' ' -f1)"
    [ -r "$SENDER_STATE" ] && previous="$(cat "$SENDER_STATE")"
    [ "$current" = "$previous" ] && return 0

    local line key value internal="" paused="" blocked=""
    local address="[a-z0-9._%+-]{1,64}@${DOMAIN}"
    local target="(${address}|${DOMAIN})"
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^([a-z_]+)[[:space:]]*=[[:space:]]*(.*)$ ]] || { log "ignoring malformed line"; continue; }
        key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
        case "$key" in
            internal_only_logins)
                if [[ "$value" =~ ^(${address}(,${address}){0,199})?$ ]]; then internal="$value"
                else log "ignoring unsafe value for $key"; fi ;;
            paused_logins)  # a higher cap: this must not fail open in a mass compromise
                if valid_list "$value" "$address" 1000; then paused="$value"
                else log "ignoring unsafe value for $key"; fi ;;
            blocked_destinations)
                if [[ "$value" =~ ^(${target}(,${target}){0,199})?$ ]]; then blocked="$value"
                else log "ignoring unsafe value for $key"; fi ;;
            *) log "ignoring key not on the allow-list: $key" ;;
        esac
    done < "$SENDER_FILE"

    local restrictions="$SUBMISSION_DEFAULT" item
    local -A action=()
    local -a list=()
    if [ -n "$internal" ]; then
        IFS=',' read -r -a list <<< "$internal"
        for item in "${list[@]}"; do action[$item]='ifinmail_internal_only'; done
    fi
    if [ -n "$paused" ]; then  # a pause outranks internal-only
        IFS=',' read -r -a list <<< "$paused"
        for item in "${list[@]}"; do action[$item]='554 5.7.1 Sending from this mailbox is paused. Contact your administrator.'; done
    fi
    : > "$SENDER_MAP.tmp"
    for item in "${!action[@]}"; do printf '%s %s\n' "$item" "${action[$item]}" >> "$SENDER_MAP.tmp"; done
    mv "$SENDER_MAP.tmp" "$SENDER_MAP"
    if [ "${#action[@]}" -gt 0 ]; then
        restrictions="check_sasl_access texthash:$SENDER_MAP, $restrictions"
    fi
    : > "$DEST_MAP.tmp"
    if [ -n "$blocked" ]; then
        IFS=',' read -r -a list <<< "$blocked"
        for item in "${list[@]}"; do
            printf '%s 554 5.7.1 Your organisation does not allow sending to this destination.\n' "$item" >> "$DEST_MAP.tmp"
        done
        restrictions="check_recipient_access texthash:$DEST_MAP, $restrictions"
    fi
    mv "$DEST_MAP.tmp" "$DEST_MAP"
    "$POSTCONF" -e "ifinmail_submission_restrictions=$restrictions"
    "$POSTFIX" reload >/dev/null 2>&1 || log "postfix reload failed (not running yet?)"
    log "applied $(basename "$SENDER_FILE")"
    echo "$current" > "$SENDER_STATE"
}

apply_once() {
    apply_file "$FILE" "$STATE" "$ALLOWED_KEYS" "$SAFE_VALUE"
    apply_file "$PLUGINS_FILE" "$PLUGINS_STATE" "$PLUGIN_KEYS" per-key
    apply_tls_policy
    apply_sender_policy
    acknowledge "$PLUGINS_STATE" postfix-plugins.applied
    acknowledge "$TLS_STATE" postfix-tls-policy.applied
    acknowledge "$SENDER_STATE" postfix-sender-policy.applied
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

# A renewed certificate (certbot writes a new file behind the live/ symlink) takes effect on reload.
watch_certificate() {
    local now
    now="$(cksum < "$CERT_FILE" 2>/dev/null)" || return 0
    if [ -n "$CERT_SEEN" ] && [ "$now" != "$CERT_SEEN" ]; then
        "$POSTFIX" reload >/dev/null 2>&1 || return 0
        log "certificate changed; reloaded"
    fi
    CERT_SEEN="$now"
}

loops=0
while :; do
    apply_once
    watch_certificate
    if [ $((loops % QUEUE_EVERY)) -eq 0 ]; then
        publish_queue
    fi
    loops=$((loops + 1))
    sleep "$INTERVAL"
done
