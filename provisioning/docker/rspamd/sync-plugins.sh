#!/usr/bin/env bash
# Applies plugin settings for Rspamd (extension point rspamd.policy).
#
# The console writes <runtime>/rspamd-plugins.conf ("key = value" lines). When it changes this
# script re-validates every key and value, renders Rspamd fragments into $OUT (included with
# .include(try=true) from local.d/multimap.conf, dmarc.conf, arc.conf, composites.conf,
# greylist.conf and ratelimit.conf), checks the whole
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
# Rspamd leaves rate limits counting but unenforced if Redis was unreachable when it started
# (verified with Rspamd 3.8.1) until it reloads, and a reload sent while Rspamd is still starting
# does not take. The watch loop therefore reloads Rspamd once it is serving, and again whenever
# Redis restarts (its run_id changes, so even a short restart is seen). This also protects the
# built-in limits in local.d/ratelimit.conf.
REDIS_ADDR="${IFINMAIL_REDIS_ADDR:-redis:6379}"
RSPAMD_SCAN_ADDR="${IFINMAIL_RSPAMD_SCAN_ADDR:-127.0.0.1:11333}"

log() { echo "ifinmail-rspamd-sync: $*"; }

DOMAIN='[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+'
# ARC seals reuse the DKIM keys the console writes (local.d/dkim_signing.conf uses the same).
DKIM_PATH='/etc/dkim/$domain.$selector.key'
DKIM_SELECTOR='default'
SENDER="([a-z0-9._%+-]{1,64}@)?${DOMAIN}"
# Per-login limit applied by ratelimit.conf alone (the plugin replaces it with its own buckets).
DOMAIN_RATE='40 / 1h'

declare -A RULES=(
    [blocked_attachment_types]='^([a-z0-9]{1,10}(,[a-z0-9]{1,10}){0,199})?$'
    [blocked_attachment_action]='^(reject|quarantine)?$'
    [dmarc_enforcement]='^(enforce|quarantine)?$'
    [arc_trusted_sealers]="^(${DOMAIN}(,${DOMAIN}){0,199})?\$"
    [arc_sealing]='^(yes|no)?$'
    [sender_block_list]="^(${SENDER}(,${SENDER}){0,199})?\$"
    [sender_allow_list]="^(${SENDER}(,${SENDER}){0,199})?\$"
    [greylisting]='^(on|off)?$'
    [send_limit_per_minute]='^([1-9][0-9]{0,3})?$'
    [send_limit_per_day]='^([1-9][0-9]{0,5})?$'
)

render() { # $1 = directory to write the fragments into
    local dir="$1" types="${VALUES[blocked_attachment_types]:-}" action dmarc
    : > "$dir/multimap.conf"
    : > "$dir/blocked_attachments.map"
    : > "$dir/dmarc.conf"
    : > "$dir/arc.conf"
    : > "$dir/arc_trusted.map"
    : > "$dir/composites.conf"
    : > "$dir/greylist.conf"
    : > "$dir/ratelimit.conf"
    local kind
    for kind in block allow; do : > "$dir/sender_${kind}_addr.map"; : > "$dir/sender_${kind}_domain.map"; done
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
    sender_rules "$dir" block "${VALUES[sender_block_list]:-}"
    sender_rules "$dir" allow "${VALUES[sender_allow_list]:-}"
    if [ -n "${VALUES[sender_allow_list]:-}" ]; then
        # An allow entry counts only when SPF or DKIM proves the sender (forged senders gain
        # nothing), and it never bypasses attachment or malware rules (those force an action).
        cat > "$dir/composites.conf" <<EOF
IFINMAIL_SENDER_ALLOWED {
  expression = "(IFINMAIL_ALLOW_ENV | IFINMAIL_ALLOW_ENV_DOMAIN | IFINMAIL_ALLOW_HDR | IFINMAIL_ALLOW_HDR_DOMAIN) & (R_DKIM_ALLOW | R_SPF_ALLOW)";
  score = -20.0;
  description = "Sender on the organisation allow list and authenticated";
}
EOF
        printf 'whitelist_symbols = ["IFINMAIL_SENDER_ALLOWED"];\n' >> "$dir/greylist.conf"
    fi
    [ "${VALUES[greylisting]:-}" = "off" ] && printf 'enabled = false;\n' >> "$dir/greylist.conf"
    local per_minute="${VALUES[send_limit_per_minute]:-}" per_day="${VALUES[send_limit_per_day]:-}"
    if [ -n "$per_minute" ] && [ -n "$per_day" ]; then
        # Separate rates with different selector values: Rspamd keys a bucket by the hash of the
        # selector value, so two rates over the same plain "user" would share one counter.
        cat > "$dir/ratelimit.conf" <<EOF
rates {
  user_minute {
    selector = "user.lower";
    bucket = { burst = $per_minute; rate = "$per_minute / 1m"; };
  }
  user_day {
    selector = "user.lower.append(\"/day\")";
    bucket = { burst = $per_day; rate = "$per_day / 1d"; };
  }
  user_to_domain {
    selector = "user.lower, rcpt_domain";
    bucket = { burst = 40; rate = "$DOMAIN_RATE"; };
  }
}
EOF
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

# sender_rules <dir> <block|allow> <comma list>: addresses and domains, envelope and From header.
sender_rules() {
    local dir="$1" kind="$2" list="$3" item upper action symbol filter where map
    [ -n "$list" ] || return 0
    IFS=',' read -r -a items <<< "$list"
    for item in "${items[@]}"; do
        if [[ "$item" == *@* ]]; then echo "$item" >> "$dir/sender_${kind}_addr.map"
        else echo "$item" >> "$dir/sender_${kind}_domain.map"; fi
    done
    upper="$(tr '[:lower:]' '[:upper:]' <<< "$kind")"
    for where in ENV HDR; do
        for map in addr domain; do
            [ -s "$dir/sender_${kind}_${map}.map" ] || continue
            symbol="IFINMAIL_${upper}_${where}"; [ "$map" = domain ] && symbol="${symbol}_DOMAIN"
            filter="email:addr"; [ "$map" = domain ] && filter="email:domain"
            {
                echo "$symbol {"
                if [ "$where" = ENV ]; then echo '  type = "from";'
                else echo '  type = "header";'; echo '  header = "From";'; fi
                echo "  filter = \"$filter\";"
                echo "  map = \"file://$OUT/sender_${kind}_${map}.map\";"
                if [ "$kind" = block ]; then
                    echo '  action = "reject";'
                    echo '  message = "Mail from this sender is not accepted by this organisation";'
                else
                    echo '  score = 0.0;'
                fi
                echo '}'
            } >> "$dir/multimap.conf"
        done
    done
}

# Check the configuration as the user Rspamd runs as: a root run leaves root-owned cache files
# (*.hsmp) in /var/lib/rspamd that Rspamd itself then cannot refresh.
config_ok() {
    if [ -z "${RSPAMADM_BIN:-}" ] && [ "$(id -u)" = 0 ] && id _rspamd >/dev/null 2>&1; then
        runuser -u _rspamd -- "$RSPAMADM" configtest >/dev/null 2>&1
    else
        "$RSPAMADM" configtest >/dev/null 2>&1
    fi
}

rspamd_serving() {
    timeout 2 bash -c "exec 3<>/dev/tcp/${RSPAMD_SCAN_ADDR%:*}/${RSPAMD_SCAN_ADDR##*:}" 2>/dev/null
}

# Prints Redis's run_id (changes on every Redis restart), or nothing if Redis is unreachable.
redis_run_id() {
    REDIS_ADDR="$REDIS_ADDR" REDIS_PASSWORD="${REDIS_PASSWORD:-}" timeout 3 bash -c '
        exec 3<>"/dev/tcp/${REDIS_ADDR%:*}/${REDIS_ADDR##*:}" || exit 1
        if [ -n "$REDIS_PASSWORD" ]; then
            printf "*2\r\n\$4\r\nAUTH\r\n\$%d\r\n%s\r\n" "${#REDIS_PASSWORD}" "$REDIS_PASSWORD" >&3
            IFS= read -r line <&3
        fi
        printf "*2\r\n\$4\r\nINFO\r\n\$6\r\nserver\r\n" >&3
        while IFS= read -r line <&3; do
            case "$line" in run_id:*) echo "${line#run_id:}" | tr -d "\r"; exit 0 ;; esac
        done' 2>/dev/null
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
        if ! config_ok; then
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

reloaded_for=''
while :; do
    apply_once
    run_id="$(redis_run_id)"
    if [ -n "$run_id" ] && [ "$run_id" != "$reloaded_for" ] && rspamd_serving; then
        if $RELOAD >/dev/null 2>&1; then
            reloaded_for="$run_id"
            log "Redis ${run_id:0:8} reachable and Rspamd serving: reloaded so its limits are enforced"
        fi
    fi
    sleep "$INTERVAL"
done
