#!/bin/sh
# certbot deploy hook — make a new certificate readable by the services that use it.
# nginx, Postfix and Dovecot watch the certificate file and reload themselves within a minute,
# so this container needs no access to Docker.
set -e

echo "Certbot deploy hook: certificate renewed"

# certbot creates live/ and archive/ as 0700; the console reads the public certificate as a
# non-root user (TLS page, expiry warnings). Private keys stay 0600.
CERTS="${CERTS:-/etc/letsencrypt}"
for dir in "$CERTS/live" "$CERTS/archive" "$CERTS/live/${MAIL_HOSTNAME:-}" "$CERTS/archive/${MAIL_HOSTNAME:-}"; do
    if [ -d "$dir" ]; then chmod 755 "$dir"; fi
done
find "$CERTS/archive" -type f \( -name 'cert*.pem' -o -name 'chain*.pem' -o -name 'fullchain*.pem' \) \
    -exec chmod 644 {} + 2>/dev/null || true
echo "  nginx, Postfix and Dovecot pick it up within a minute."
