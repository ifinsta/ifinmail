#!/bin/sh
# ifinmail-log-rotate <log file>
# Keeps the Postfix log the console's threat digest reads from growing without bound: when it
# passes MAIL_LOG_MAX_BYTES (default 16 MiB) it is moved to <file>.1 (replacing the previous one),
# a fresh world-readable file takes its place and Postfix is told to reopen it. The digest reads
# both files, so a rotation loses nothing it had not read. docker logs is unaffected: the
# entrypoint forwards the file to the container output.
file="$1"
max="${MAIL_LOG_MAX_BYTES:-16777216}"
while :; do
    sleep "${LOG_ROTATE_INTERVAL:-30}"
    size="$(wc -c < "$file" 2>/dev/null)" || continue
    [ "${size:-0}" -gt "$max" ] || continue
    mv -f "$file" "$file.1" || continue
    : > "$file" && chmod 0644 "$file"
    pkill -x postlogd  # postlogd is started again on the next line and opens the new file
    echo "log-rotate: $file passed $max bytes; rotated"
done
