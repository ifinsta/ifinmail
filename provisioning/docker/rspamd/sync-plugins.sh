#!/usr/bin/env bash
# Applies plugin settings for Rspamd (extension point rspamd.policy).
#
# The console writes <runtime>/rspamd-plugins.conf ("key = value" lines). When it changes this
# script re-validates every key and value, renders Rspamd fragments into $OUT (included with
# .include(try=true) from local.d/multimap.conf, dmarc.conf and arc.conf), checks the whole
# configuration with `rspamadm configtest`, and only then reloads Rspamd. A configuration that
# fails the test is rolled back and not acknowledged. The SHA-256 of an applied file is written to
# <status>/rspamd-plugins.applied so the console can show "Applied".
#
#   sync-plugins.sh          watch forever (every 10 s)
#   sync-plugins.sh --once   apply once and exit (start-up and tests)
set -u

FILE="${IFINMAIL_RSPAMD_PLUGINS_FILE:-/var/lib/ifinmail/runtime/rspamd-plugins.conf}"
STATE="${IFINMAIL_RSPAMD_PLUGINS_STATE:-/var/run/ifinmail-rspamd-plugins.sha256}"
STATUS_DIR="${IFINMAIL_STATUS_DIR:-/var/lib/ifinmail/status}"
OUT="${IFINMAIL_RSPAMD_OUT:-/var/lib/ifinmail-rspamd}"
RSPAMADM="${RSPAMADM_BIN:-rspamadm}"
# PID 1 is Rspamd once the entrypoint has exec'd it; the start-up pass passes RSPAMD_RELOAD=true.
RELOAD="${RSPAMD_RELOAD:-kill -HUP 1}"
INTERVAL="${IFINMAIL_SYNC_INTERVAL:-10}"

log() { echo "ifinmail-rspamd-sync: $*"; }

DOMAIN='[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+'
# ARC seals reuse the DKIM keys the console writes (local.d/dkim_signing.conf uses the same).
DKIM_PATH='/etc/dkim/$domain.$selector.key'
DKIM_SELECTOR='default'

declare -A RULES=(
    [blocked_attachment_types]='^([a-z0-9]{1,10}(,[a-z0-9]{1,10}){0,199})?$'
    [blocked_attachment_action]='^(reject|quarantine)?$'
    [dmarc_enforcement]='^(enforce|quarantine)?$'
    [arc_trusted_sealers]="^(${DOMAIN}(,${DOMAIN}){0,199})?\$"
    [arc_sealing]='^(yes|no)?$'
)

render() { # $1 = directory to write the fragments into
    local dir="$1" types="${VALUES[blocked_attachment_types]:-}" action dmarc
    : > "$dir/multimap.conf"
    : > "$dir/blocked_attachments.map"
    : > "$dir/dmarc.conf"
    : > "$dir/arc.conf"
    : > "$dir/arc_trusted.map"
    if [ -n "$types" ]; then
        action="reject"
        [ "${VALUES[blocked_attachment_action]:-reject}" = "quarantine" ] && action="add header"
        local ext
        IFS=',' read -r -a exts <<< "$types"
        for ext in "${exts[@]}"; do printf '/\\.%s$/i\n' "$ext" >> "$dir/blocked_attachments.map"; done
        cat > "$dir/multimap.conf" <<EOF
IFINMAIL_BLOCKED_ATTACHMENT {
  type = "filename";
  map = "file://$OUT/blocked_attachments.map";
  regexp = true;
  action = "$action";
  message = "Attachments of this type are not accepted by this server";
  description = "Attachment type blocked by the Attachment guard plugin";
}
EOF
    fi
    dmarc="${VALUES[dmarc_enforcement]:-}"
    if [ "$dmarc" = "enforce" ]; then
        printf 'actions {\n  quarantine = "add header";\n  reject = "reject";\n}\n' > "$dir/dmarc.conf"
    elif [ "$dmarc" = "quarantine" ]; then
        printf 'actions {\n  quarantine = "add header";\n  reject = "add header";\n}\n' > "$dir/dmarc.conf"
    fi
    local sealers="${VALUES[arc_trusted_sealers]:-}"
    if [ -n "$sealers" ]; then
        tr ',' '\n' <<< "$sealers" > "$dir/arc_trusted.map"
        printf 'whitelisted_signers_map = "file://%s/arc_trusted.map";\nadjust_dmarc = true;\n' \
            "$OUT" >> "$dir/arc.conf"
    fi
    if [ "${VALUES[arc_sealing]:-}" = "yes" ]; then
        cat >> "$dir/arc.conf" <<EOF
path = "$DKIM_PATH";
selector = "$DKIM_SELECTOR";
try_fallback = true;
sign_inbound = true;
use_domain = "recipient";
allow_hdrfrom_mismatch = true;
EOF
    fi
}

apply_once() {
    [ -r "$FILE" ] || return 0
    local current previous=""
    current="$(sha256sum "$FILE" | cut -d' ' -f1)"
    [ -r "$STATE" ] && previous="$(cat "$STATE")"
    if [ "$current" != "$previous" ]; then
        declare -gA VALUES=()
        local line key value
        while IFS= read -r line || [ -n "$line" ]; do
            [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
            if [[ ! "$line" =~ ^([a-z_]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
                log "ignoring malformed line"; continue
            fi
            key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
            if [ -z "${RULES[$key]+set}" ]; then log "ignoring key not on the allow-list: $key"; continue; fi
            if [[ ! "$value" =~ ${RULES[$key]} ]]; then log "ignoring unsafe value for $key"; continue; fi
            VALUES[$key]="$value"
        done < "$FILE"

        mkdir -p "$OUT"
        local backup
        backup="$(mktemp -d)"
        cp -a "$OUT/." "$backup/" 2>/dev/null || true
        render "$OUT"
        chmod 644 "$OUT"/* 2>/dev/null || true
        if ! "$RSPAMADM" configtest >/dev/null 2>&1; then
            log "configuration test failed; keeping the previous rules"
            find "$OUT" -mindepth 1 -maxdepth 1 -type f -delete
            cp -a "$backup/." "$OUT/" 2>/dev/null || true
            rm -rf "$backup"
            return 1
        fi
        rm -rf "$backup"
        if ! $RELOAD >/dev/null 2>&1; then
            log "reload failed; will retry (not acknowledged)"
            return 1
        fi
        echo "$current" > "$STATE"
        log "applied $(basename "$FILE")"
    fi
    acknowledge
}

acknowledge() {
    [ -r "$STATE" ] && [ -d "$STATUS_DIR" ] && [ -w "$STATUS_DIR" ] || return 0
    local applied
    applied="$(cat "$STATE")"
    [ "$(cat "$STATUS_DIR/rspamd-plugins.applied" 2>/dev/null)" = "$applied" ] && return 0
    printf '%s\n' "$applied" > "$STATUS_DIR/rspamd-plugins.applied.tmp" \
        && mv "$STATUS_DIR/rspamd-plugins.applied.tmp" "$STATUS_DIR/rspamd-plugins.applied"
    chmod 644 "$STATUS_DIR/rspamd-plugins.applied" 2>/dev/null || true
}

if [ "${1:-}" = "--once" ]; then
    apply_once
    exit 0
fi

while :; do
    apply_once
    sleep "$INTERVAL"
done
