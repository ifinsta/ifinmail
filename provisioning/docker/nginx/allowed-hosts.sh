#!/bin/sh
# allowed-hosts.sh: prints the nginx `map` that says which Host headers this server answers.
#
# The list is the console's own ALLOWED_HOSTS (plus the mail host, the server address and the
# local names), so nginx and Django cannot disagree. A request for any other Host is scanner
# traffic (names read from certificate logs, IP scans with made-up Hosts): nginx closes the
# connection (444) without waking Django or the database. The setup names (autoconfig.,
# autodiscover., mta-sts.) are not in this list on purpose; their few real paths are let through
# by the map in ifinmail.conf. An empty list or "*" allows everything (fail open: a typo must
# never take the console off the air).
set -f  # "*" must reach the case below as a star, not as a list of files
all=0
out=""
seen=" "
add() {
    name="$(printf '%s' "$1" | tr 'A-Z' 'a-z' | tr -d ' \t\r')"
    case "$name" in
        '') return ;;
        '*') all=1; return ;;
        *[!a-z0-9.:_-]*) return ;;  # anything that is not a plausible host name is ignored
    esac
    case "$seen" in *" $name "*) return ;; esac  # nginx refuses a map with a repeated key
    seen="$seen$name "
    out="$out    $name 1;
"
}
IFS=','
for item in ${ALLOWED_HOSTS:-}; do add "$item"; done
for item in "${MAIL_HOSTNAME:-}" "${SERVER_IP:-}" localhost 127.0.0.1; do add "$item"; done
unset IFS
[ -z "${ALLOWED_HOSTS:-}" ] && all=1
printf 'map $host $ifm_host_ok {\n    hostnames;\n'
if [ "$all" = 1 ]; then
    printf '    default 1;\n'
else
    printf '    default 0;\n%s' "$out"
fi
printf '}\n'
