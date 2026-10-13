#!/bin/sh
# ifinmail firewall agent.
#
# The console renders /runtime/firewall.nft (a complete, self-replacing nftables rule set for
# table "inet ifinmail"). This agent validates it, applies it atomically, and reports the outcome
# in /runtime/firewall-status.json so the console can show whether the rules are really in force.
# Only the "inet ifinmail" table is ever touched; SSH and everything else are left alone.
set -u

RUNTIME="${RUNTIME:-/runtime}"
RULES="$RUNTIME/firewall.nft"
STATUS="$RUNTIME/firewall-status.json"
POLL="${FIREWALL_POLL_SECONDS:-5}"
HEARTBEAT="${FIREWALL_HEARTBEAT_SECONDS:-30}"
applied=""
ok=false
# Scan ban: nginx's JSON access log (read-only volume) is read every poll; an address that is
# refused SCAN_BAN_THRESHOLD times within about 15 seconds (a scanner working through a word list
# of /.env, /.git/config ...) goes straight into the penalty box, on every port. The threat digest
# only looks every ten minutes; this acts within seconds. Static files are not counted (a stale
# page can miss several), and the exempt set (this server, its own side, the allow-list) is never
# banned. It only runs while the console's rules include the penalty box (the cap is on).
ACCESS_LOG="${ACCESS_LOG:-/var/log/ifinmail/access.json}"
SCAN_LIMIT="${SCAN_BAN_THRESHOLD:-30}"
SCAN_DIR="${SCAN_STATE_DIR:-/tmp/scan}"
log_offset=-1
scan_bans=0
mkdir -p "$SCAN_DIR" && : > "$SCAN_DIR/prev1" && : > "$SCAN_DIR/prev2"
message="Waiting for rules from the console."

# Addresses the kernel put in the penalty box (over a per-address rate cap), counted for the console.
penalised() {
    n=0
    for set in penalty4 penalty6; do
        c="$(nft list set inet ifinmail "$set" 2>/dev/null | grep -o 'expires' | wc -l)"
        n=$(( n + ${c:-0} ))
    done
    echo "$n"
}

# Addresses refused (400/403/404/405/444, static files aside) in the log since the last look.
refused_since_last_look() {
    awk '
        match($0, /"ip": *"[^"]+"/) { ip = substr($0, RSTART, RLENGTH); sub(/^"ip": *"/, "", ip); sub(/"$/, "", ip) }
        match($0, /"st": *[0-9]+/) { st = substr($0, RSTART, RLENGTH); sub(/^"st": */, "", st) }
        match($0, /"uri": *"[^"]*"/) { uri = substr($0, RSTART, RLENGTH); sub(/^"uri": *"/, "", uri); sub(/"$/, "", uri) }
        ip != "" && (st == 400 || st == 403 || st == 404 || st == 405 || st == 444) && uri !~ /^\/static\// { print ip }
        { ip = ""; st = ""; uri = "" }
    '
}

scan_log() {
    [ -r "$ACCESS_LOG" ] || return 0
    nft list set inet ifinmail penalty4 >/dev/null 2>&1 || return 0
    size="$(wc -c < "$ACCESS_LOG" 2>/dev/null)" || return 0
    if [ "$log_offset" -lt 0 ]; then
        log_offset=$size  # the past was the digest's business: start at the end
        return 0
    fi
    [ "$size" -lt "$log_offset" ] && log_offset=0  # rotated: read the new file from the start
    if [ "$size" -gt "$log_offset" ]; then
        tail -c +$(( log_offset + 1 )) "$ACCESS_LOG" | head -c $(( size - log_offset )) \
            | refused_since_last_look > "$SCAN_DIR/now"
    else
        : > "$SCAN_DIR/now"
    fi
    log_offset=$size
    for ip in $(cat "$SCAN_DIR/now" "$SCAN_DIR/prev1" "$SCAN_DIR/prev2" \
            | awk -v limit="$SCAN_LIMIT" '{ n[$1]++ } END { for (a in n) if (n[a] >= limit) print a }'); do
        case "$ip" in *:*) family=6 ;; *) family=4 ;; esac
        nft get element inet ifinmail "exempt$family" "{ $ip }" >/dev/null 2>&1 && continue
        nft get element inet ifinmail "penalty$family" "{ $ip }" >/dev/null 2>&1 && continue
        if nft add element inet ifinmail "penalty$family" "{ $ip }" 2>/dev/null; then
            scan_bans=$(( scan_bans + 1 ))
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): scan-ban $ip (refused $SCAN_LIMIT+ times in ~15 s)"
        fi
    done
    mv -f "$SCAN_DIR/prev1" "$SCAN_DIR/prev2"
    mv -f "$SCAN_DIR/now" "$SCAN_DIR/prev1"
}

report() {
    msg="$(printf '%s' "$message" | tr '\n"\\' '  /' | cut -c1-300)"
    printf '{"updated":"%s","ok":%s,"sha256":"%s","message":"%s","penalised":%s,"scan_bans":%s}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ok" "$applied" "$msg" "$(penalised)" "$scan_bans" \
        > "$STATUS.tmp" \
        && mv "$STATUS.tmp" "$STATUS"
}

apply_rules() {
    digest="$(sha256sum "$RULES" | cut -d' ' -f1)"
    if out="$(nft -c -f "$RULES" 2>&1)" && out="$(nft -f "$RULES" 2>&1)"; then
        applied="$digest"; ok=true; message="Rules applied."
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): applied $digest"
    else
        applied="$digest"; ok=false; message="Rules rejected, previous rules kept: $out"
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): $message"
    fi
}

cleanup() {
    # Stopping the agent removes our table so a stale rule set can never outlive it.
    nft delete table inet ifinmail 2>/dev/null
    exit 0
}
trap cleanup TERM INT

echo "=== ifinmail firewall agent ==="
since_report=$HEARTBEAT
while :; do
    if [ -r "$RULES" ]; then
        digest="$(sha256sum "$RULES" | cut -d' ' -f1)"
        if [ "$digest" != "$applied" ]; then
            apply_rules
            report
            since_report=0
        fi
    fi
    scan_log
    if [ "$since_report" -ge "$HEARTBEAT" ]; then
        report
        since_report=0
    fi
    sleep "$POLL" &
    wait $!
    since_report=$(( since_report + POLL ))
done
