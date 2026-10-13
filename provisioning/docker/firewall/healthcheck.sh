#!/bin/sh
# Healthy means the agent is alive and doing its job:
#   * its heartbeat file is fresh (the agent rewrites it every FIREWALL_HEARTBEAT_SECONDS),
#   * nftables answers (NET_ADMIN works),
#   * when rules were applied, the "inet ifinmail" table really exists in the kernel,
#   * and the last rule set the console sent was not rejected (a rejected set means the intended
#     policy is NOT in force, which is the one thing this container exists to prevent).
# "Waiting for rules from the console" is healthy: nothing has been asked of it yet.
set -u
status="${RUNTIME:-/runtime}/firewall-status.json"
max_age="${FIREWALL_HEALTH_MAX_AGE:-120}"

[ -r "$status" ] || { echo "no status file yet"; exit 1; }
age=$(( $(date +%s) - $(stat -c %Y "$status") ))
[ "$age" -le "$max_age" ] || { echo "agent silent for ${age}s"; exit 1; }
nft list tables >/dev/null 2>&1 || { echo "nftables not reachable"; exit 1; }

body="$(cat "$status")"
case "$body" in
    *'"ok":true'*)
        nft list table inet ifinmail >/dev/null 2>&1 || { echo "rules reported applied but table is missing"; exit 1; }
        ;;
    *'"ok":false'*)
        case "$body" in
            *'"sha256":""'*) ;;  # nothing applied yet: waiting for the console
            *) echo "last rule set was rejected"; exit 1 ;;
        esac
        ;;
esac
exit 0
