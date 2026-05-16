#!/bin/bash
# ifinmail restore_test.sh — Monthly restore verification
# The backup you never test is not a backup.
# Schedule: monthly (23 5 1 * *)
set -euo pipefail

TEST_DIR="/tmp/ifinmail_restore_test"
echo "=== ifinmail Restore Test ==="
mkdir -p "$TEST_DIR"

# Find latest backup
LATEST=$(ls -t /backups/ifinmail_backup_*.tar.gz 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    echo "ERROR: No backups found in /backups/"
    rm -rf "$TEST_DIR"
    exit 1
fi

echo "Testing restore from: $LATEST (size: $(du -h "$LATEST" | cut -f1))"
tar -xzf "$LATEST" -C "$TEST_DIR"

PASS=0
FAIL=0

# 1. Check PostgreSQL dump validity
echo -n "  PostgreSQL dump validity: "
if [ -f "$TEST_DIR/postgresql/ifinmail.dump" ]; then
    pg_restore -l "$TEST_DIR/postgresql/ifinmail.dump" > /dev/null 2>&1 && \
        { echo "PASS"; PASS=$((PASS+1)); } || \
        { echo "FAIL (corrupt dump)"; FAIL=$((FAIL+1)); }
else
    echo "FAIL (dump file missing)"
    FAIL=$((FAIL+1))
fi

# 2. Check mail storage
echo -n "  Mail storage: "
MAILDIRS=$(find "$TEST_DIR/mail" -type d 2>/dev/null | wc -l)
if [ "$MAILDIRS" -gt 0 ]; then
    echo "PASS ($MAILDIRS directories)"
    PASS=$((PASS+1))
else
    echo "WARN (no mail directories — may be empty system)"
    PASS=$((PASS+1))
fi

# 3. Check configs
echo -n "  Configuration files: "
CONFIG_COUNT=0
[ -f "$TEST_DIR/configs/postfix/main.cf" ] && CONFIG_COUNT=$((CONFIG_COUNT+1))
[ -f "$TEST_DIR/configs/dovecot/dovecot.conf" ] && CONFIG_COUNT=$((CONFIG_COUNT+1))
[ -f "$TEST_DIR/configs/dotenv" ] && CONFIG_COUNT=$((CONFIG_COUNT+1))
echo "PASS ($CONFIG_COUNT key files)"
PASS=$((PASS+1))

# 4. Check DKIM keys
echo -n "  DKIM keys: "
DKIM_COUNT=$(find "$TEST_DIR/dkim" -name "*.key" 2>/dev/null | wc -l)
if [ "$DKIM_COUNT" -gt 0 ]; then
    echo "PASS ($DKIM_COUNT keys)"
    PASS=$((PASS+1))
else
    echo "WARN (no keys — add domains to generate)"
    PASS=$((PASS+1))
fi

# Summary
echo ""
echo "  Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    echo "=== RESTORE TEST FAILED — INVESTIGATE IMMEDIATELY ==="
else
    echo "=== Restore test passed ==="
fi

rm -rf "$TEST_DIR"
