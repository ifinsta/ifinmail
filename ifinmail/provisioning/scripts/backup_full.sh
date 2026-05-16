#!/bin/bash
# ifinmail backup_full.sh — Full backup including PostgreSQL, mail, configs, DKIM
# Matches proposal Section 14.2 backup scope
# Schedule: daily via cron (17 3 * * *)
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_ROOT="/backups/${TIMESTAMP}"
RETENTION_DAYS=30

echo "=== ifinmail Backup: $TIMESTAMP ==="

# 1. PostgreSQL dump
echo "[1/5] Backing up PostgreSQL..."
mkdir -p "$BACKUP_ROOT/postgresql"
docker compose -f /opt/ifinmail/provisioning/docker/docker-compose.yml exec -T postgres \
    pg_dump -U ifinmail -Fc ifinmail > "$BACKUP_ROOT/postgresql/ifinmail.dump"
# Schema-only for quick reference
docker compose -f /opt/ifinmail/provisioning/docker/docker-compose.yml exec -T postgres \
    pg_dump -U ifinmail --schema-only ifinmail > "$BACKUP_ROOT/postgresql/ifinmail_schema.sql"

# 2. Mail storage (Maildir)
echo "[2/5] Backing up mail storage..."
mkdir -p "$BACKUP_ROOT/mail"
docker compose -f /opt/ifinmail/provisioning/docker/docker-compose.yml run --rm \
    -v "$BACKUP_ROOT/mail:/backup_mail" alpine:latest \
    sh -c "cp -a /var/mail/vhosts /backup_mail/" 2>/dev/null || \
    echo "  No mail data volume available (may not be running)"

# 3. Configuration files
echo "[3/5] Backing up configuration..."
mkdir -p "$BACKUP_ROOT/configs"
cp -r /opt/ifinmail/provisioning/docker/postfix "$BACKUP_ROOT/configs/"
cp -r /opt/ifinmail/provisioning/docker/dovecot "$BACKUP_ROOT/configs/"
cp -r /opt/ifinmail/provisioning/docker/rspamd/local.d "$BACKUP_ROOT/configs/rspamd"
cp /opt/ifinmail/provisioning/.env "$BACKUP_ROOT/configs/dotenv"

# 4. DKIM keys (separate — these are irreplaceable)
echo "[4/5] Backing up DKIM keys..."
mkdir -p "$BACKUP_ROOT/dkim"
cp -r /opt/ifinmail/provisioning/docker/dkim "$BACKUP_ROOT/dkim/keys"
chmod -R 600 "$BACKUP_ROOT/dkim"

# 5. Manifest
echo "[5/5] Creating manifest..."
cat > "$BACKUP_ROOT/MANIFEST.txt" << MANIFEST
Backup: $TIMESTAMP
Host: $(hostname)
Date: $(date -Iseconds)
Contents:
  - PostgreSQL dump (ifinmail.dump + schema)
  - Mail storage (/var/mail/vhosts)
  - Configuration (postfix, dovecot, rspamd, .env)
  - DKIM keys
MANIFEST

# Compress
echo "Compressing backup..."
tar -czf "/backups/ifinmail_backup_${TIMESTAMP}.tar.gz" -C "$BACKUP_ROOT" .
rm -rf "$BACKUP_ROOT"

# Clean old backups
echo "Cleaning backups older than $RETENTION_DAYS days..."
find /backups -name "ifinmail_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

# Report
SIZE=$(du -h "/backups/ifinmail_backup_${TIMESTAMP}.tar.gz" | cut -f1)
echo "=== Backup complete: /backups/ifinmail_backup_${TIMESTAMP}.tar.gz ($SIZE) ==="
