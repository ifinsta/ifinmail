#!/bin/sh
# ifinmail-log-rotate <log file>
# Keeps the Rspamd log the console's threat digest reads from growing without bound: past
# MAIL_LOG_MAX_BYTES (default 16 MiB) it is moved to <file>.1 (replacing the previous one), a
# fresh world-readable file takes its place and Rspamd is told (SIGUSR1) to reopen its log.
file="$1"
max="${MAIL_LOG_MAX_BYTES:-16777216}"
while :; do
    sleep "${LOG_ROTATE_INTERVAL:-30}"
    size="$(wc -c < "$file" 2>/dev/null)" || continue
    [ "${size:-0}" -gt "$max" ] || continue
    mv -f "$file" "$file.1" || continue
    : > "$file" && chown _rspamd:_rspamd "$file" && chmod 0644 "$file"
    kill -USR1 1
    echo "log-rotate: $file passed $max bytes; rotated"
done
