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

report() {
    msg="$(printf '%s' "$message" | tr '\n"\\' '  /' | cut -c1-300)"
    printf '{"updated":"%s","ok":%s,"sha256":"%s","message":"%s","penalised":%s}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ok" "$applied" "$msg" "$(penalised)" > "$STATUS.tmp" \
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
    if [ "$since_report" -ge "$HEARTBEAT" ]; then
        report
        since_report=0
    fi
    sleep "$POLL" &
    wait $!
    since_report=$(( since_report + POLL ))
done
