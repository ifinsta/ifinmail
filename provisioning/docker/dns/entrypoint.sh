#!/bin/sh
# ifinmail dns container: run Knot DNS and keep it in step with what the console publishes.
#
#   * the console writes /runtime/dns/zones/*.zone and /runtime/dns/knot.generated.conf
#   * this script reloads Knot within seconds of either changing
#   * after each reload, the DNSSEC DS records for every zone are written to /runtime/dns/ds/
#     so the console can show them (publish them at the registrar once)
set -u

RUNTIME="${RUNTIME:-/runtime}"
CONF="${KNOT_CONF:-/etc/knot/knot.conf}"
POLL="${DNS_POLL_SECONDS:-5}"
DIR="$RUNTIME/dns"

mkdir -p "$DIR/zones" "$DIR/ds"
[ -f "$DIR/knot.generated.conf" ] || echo "# no zones yet" > "$DIR/knot.generated.conf"
# The console (uid 1000) writes the zones and the generated config; this container only writes ds/.
# Without this, whichever container creates the directory first leaves it root-owned and no zone
# is ever published.
APP_UID="${APP_UID:-1000}"
chown "$APP_UID:$APP_UID" "$DIR" "$DIR/zones" "$DIR/knot.generated.conf"

fingerprint() {
    # Content of every generated file, so an edit in place is noticed.
    cat "$DIR/knot.generated.conf" "$DIR"/zones/*.zone 2>/dev/null | sha256sum | cut -d' ' -f1
}

export_ds() {
    for zone_file in "$DIR"/zones/*.zone; do
        [ -e "$zone_file" ] || continue
        zone="$(basename "$zone_file" .zone)"
        out="$DIR/ds/$zone.ds"
        if ds="$(keymgr -c "$CONF" "$zone" ds 2>/dev/null)" && [ -n "$ds" ]; then
            printf '%s\n' "$ds" > "$out.tmp" && mv "$out.tmp" "$out"
        fi
    done
}

echo "=== ifinmail dns (Knot) ==="
knotc -c "$CONF" conf-check || { echo "initial configuration is invalid"; exit 1; }

knotd -c "$CONF" &
KNOT_PID=$!
trap 'kill "$KNOT_PID" 2>/dev/null; wait "$KNOT_PID"; exit 0' TERM INT

# Wait for the control socket, then take the first DS snapshot.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    knotc -c "$CONF" status >/dev/null 2>&1 && break
    sleep 1
done
applied="$(fingerprint)"
sleep 2
export_ds

while kill -0 "$KNOT_PID" 2>/dev/null; do
    sleep "$POLL"
    current="$(fingerprint)"
    if [ "$current" != "$applied" ]; then
        if knotc -c "$CONF" conf-check >/dev/null 2>&1; then
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): zone data changed, reloading"
            knotc -c "$CONF" reload || echo "  reload failed; keeping the previous zones"
            applied="$current"
            sleep 2
            export_ds
        else
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ): generated configuration is invalid; not reloading"
            applied="$current"
        fi
    fi
done
wait "$KNOT_PID"
