#!/bin/sh
# Called by Dovecot (service quota-warning, as vmail) when a mailbox crosses a quota threshold.
#   $1 = percentage reached (80 or 95), $2 = the mailbox address
# Puts a short notice in that mailbox's Inbox with Dovecot's own delivery tool. The notice is
# delivered with quota enforcement off for this one message, so it cannot bounce for being over.
set -eu
PERCENT="${1:-}"
USER_ADDRESS="${2:-}"
case "$PERCENT" in ''|*[!0-9]*) echo "quota-warning: bad percentage" >&2; exit 1 ;; esac
if ! printf '%s' "$USER_ADDRESS" | grep -Eq '^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}$'; then
    echo "quota-warning: bad address" >&2; exit 1
fi
DOMAIN="${USER_ADDRESS#*@}"
LDA="${DOVECOT_LDA:-/usr/lib/dovecot/dovecot-lda}"

"$LDA" -d "$USER_ADDRESS" -o "plugin/quota=maildir:User quota:noenforcing" -o info_log_path=/dev/null <<MSG
From: Mail server <postmaster@${DOMAIN}>
To: <${USER_ADDRESS}>
Subject: Your mailbox is ${PERCENT}% full
Date: $(date -R)
Auto-Submitted: auto-generated
Content-Type: text/plain; charset=utf-8

Your mailbox ${USER_ADDRESS} has used ${PERCENT}% of its storage.

When it is full, new messages to you are refused and their senders get a bounce.
Delete messages you no longer need, empty Trash, or ask your administrator for more space.
MSG
