#!/bin/sh
# cert-watch.sh <certificate> <command...>
# Runs the command (e.g. "nginx -s reload") whenever the certificate file's content changes, so a
# renewal takes effect within a minute without anything restarting containers. The command is
# retried on the next pass if it fails.
file="$1"
shift
last="$(cksum < "$file" 2>/dev/null)"
while :; do
    sleep "${CERT_WATCH_INTERVAL:-60}"
    now="$(cksum < "$file" 2>/dev/null)" || continue
    [ -n "$now" ] && [ "$now" != "$last" ] || continue
    if "$@"; then
        last="$now"
        echo "cert-watch: $file changed; ran: $*"
    fi
done
