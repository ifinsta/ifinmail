#!/usr/bin/env bash
# ifinmail firewall.sh — configure host firewall using ufw
# Run once after initial server setup.
set -euo pipefail

echo "=== ifinmail Firewall Configuration ==="

# Check if ufw is available
if ! command -v ufw >/dev/null 2>&1; then
    echo "Installing ufw..."
    apt-get update -qq && apt-get install -y -qq ufw
fi

echo "Resetting firewall to defaults..."
ufw --force reset >/dev/null

# Default policies: deny incoming, allow outgoing
ufw default deny incoming
ufw default allow outgoing

# SSH — critical: allow before enabling firewall
echo "Allowing SSH (port 22)..."
ufw allow 22/tcp comment 'SSH'

# HTTP/HTTPS (nginx)
echo "Allowing HTTP/HTTPS..."
ufw allow 80/tcp comment 'HTTP (nginx)'
ufw allow 443/tcp comment 'HTTPS (nginx)'

# SMTP
echo "Allowing SMTP..."
ufw allow 25/tcp comment 'SMTP (Postfix)'

# Submission (authenticated SMTP)
echo "Allowing Submission..."
ufw allow 587/tcp comment 'Submission (Postfix)'
ufw allow 465/tcp comment 'SMTPS (Postfix legacy)'

# IMAP
echo "Allowing IMAP..."
ufw allow 143/tcp comment 'IMAP (Dovecot)'
ufw allow 993/tcp comment 'IMAPS (Dovecot)'

# Optional: monitoring web UI (only if needed externally)
# ufw allow 11334/tcp comment 'Rspamd web UI'

# Enable the firewall
echo ""
echo "Rules to be applied:"
ufw show added

echo ""
read -rp "Enable firewall now? [y/N] " confirm
if [[ "${confirm,,}" == "y" ]]; then
    ufw --force enable
    echo "Firewall enabled."
    ufw status verbose
else
    echo "Skipping enable. Run 'ufw enable' manually when ready."
fi

echo ""
echo "=== Firewall configuration complete ==="
