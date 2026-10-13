#!/bin/sh
# log-rotate.sh <log file>
# Keeps the JSON access log from growing without bound: when it passes ACCESS_LOG_MAX_BYTES
# (default 16 MiB) the file is moved to <file>.1 (replacing the previous one) and nginx reopens
# it. The console's threat digest reads both files, so a rotation loses nothing it had not read.
# Under a flood the log can grow fast; the cap is what keeps the volume small.
file="$1"
max="${ACCESS_LOG_MAX_BYTES:-16777216}"
while :; do
    sleep "${LOG_ROTATE_INTERVAL:-30}"
    size="$(wc -c < "$file" 2>/dev/null)" || continue
    [ "${size:-0}" -gt "$max" ] || continue
    mv -f "$file" "$file.1" && nginx -s reopen && echo "log-rotate: $file passed $max bytes; rotated"
done
