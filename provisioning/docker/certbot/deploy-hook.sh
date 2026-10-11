#!/bin/sh
# certbot deploy hook — reload services after successful certificate renewal
set -e

echo "Certbot deploy hook: certificate renewed, restarting services..."

# certbot creates live/ and archive/ as 0700; the console reads the public certificate as a
# non-root user (TLS page, expiry warnings). Private keys stay 0600.
CERTS="${CERTS:-/etc/letsencrypt}"
for dir in "$CERTS/live" "$CERTS/archive" "$CERTS/live/${MAIL_HOSTNAME:-}" "$CERTS/archive/${MAIL_HOSTNAME:-}"; do
    if [ -d "$dir" ]; then chmod 755 "$dir"; fi
done
find "$CERTS/archive" -type f \( -name 'cert*.pem' -o -name 'chain*.pem' -o -name 'fullchain*.pem' \) \
    -exec chmod 644 {} + 2>/dev/null || true

COMPOSE_FILE="${COMPOSE_FILE:-/config/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-/config/.env}"

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" restart nginx postfix dovecot postgres 2>/dev/null || {
    echo "WARNING: Could not restart services via docker compose."
    echo "Run 'make reload' manually to pick up the new certificate."
}

echo "  Services restarted."
