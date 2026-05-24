#!/usr/bin/env sh
set -eu

sed_escape() {
    printf "%s" "$1" | sed 's/[|&]/\\&/g'
}

: "${MAIL_HOSTNAME:=mail.ifinsta.online}"
: "${MAIL_DOMAIN:=ifinsta.online}"
: "${POSTFIX_DB_PASSWORD:=postfix_password_change_me}"

MAIL_HOSTNAME_ESC="$(sed_escape "$MAIL_HOSTNAME")"
MAIL_DOMAIN_ESC="$(sed_escape "$MAIL_DOMAIN")"
POSTFIX_DB_PASSWORD_ESC="$(sed_escape "$POSTFIX_DB_PASSWORD")"

sed \
    -e "s|__MAIL_HOSTNAME__|$MAIL_HOSTNAME_ESC|g" \
    -e "s|__MAIL_DOMAIN__|$MAIL_DOMAIN_ESC|g" \
    /etc/postfix/main.cf.template > /etc/postfix/main.cf

for template in /etc/postfix/pgsql-templates/*.cf; do
    map="/etc/postfix/pgsql/$(basename "$template")"
    sed "s|__POSTFIX_DB_PASSWORD__|$POSTFIX_DB_PASSWORD_ESC|g" "$template" > "$map"
    chown root:postfix "$map"
    chmod 640 "$map"
done

exec "$@"
