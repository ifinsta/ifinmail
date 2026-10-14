#!/bin/sh
# Radicale plus the directory mirror. The mirror is a helper: if it stops, calendars and
# contacts keep working, and the healthcheck notices a stale heartbeat.
set -eu
python /usr/local/bin/directory-sync.py &
exec python -m radicale --config /etc/radicale/config
