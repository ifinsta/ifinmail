"""Space budget — how much mailbox quota the mail volume can still promise.

The budget is based on what mail can actually grow into, not on raw disk size:

    available  = disk free + mail already stored by quota-limited mailboxes
    headroom   = available - allocated quotas

Disk free alone would double-count stored mail (it is both "used" and part of
the promises); disk total would ignore everything else sharing the volume.
It never blocks an action: quotas are promises, and deliberate overcommit is a
valid admin choice — the console just makes the numbers visible and warns when
the promises cannot fit.
"""

from __future__ import annotations

import logging
import os
import shutil
from contextlib import suppress

from django.db import DatabaseError
from django.db.models import Count, Q, Sum

from ..models import Mailbox
from ..types.quota import QuotaBudget

logger = logging.getLogger('backend')

_MAIL_VHOSTS_DIR = os.environ.get('MAIL_VHOSTS_DIR', '/var/mail/vhosts')
_APP_DIR = os.environ.get('APP_DIR', '/app')


def _disk_usage() -> tuple[int | None, int | None]:
    """(total, free) of the filesystem holding the mail volume, or (None, None)."""
    paths = os.environ.get('DISK_CHECK_PATHS', f'{_MAIL_VHOSTS_DIR},{_APP_DIR},/')
    for path in paths.split(','):
        candidate = path.strip()
        if not candidate or not os.path.exists(candidate):
            continue
        try:
            usage = shutil.disk_usage(candidate)
            return usage.total, usage.free
        except OSError:
            continue
    return None, None


def _allocation() -> tuple[int, int, int]:
    """(sum of finite quotas, mailbox count, unlimited count)."""
    try:
        totals = Mailbox.objects.aggregate(
            allocated=Sum('quota_bytes'),
            count=Count('id'),
            unlimited=Count('id', filter=Q(quota_bytes=0) | Q(quota_bytes__isnull=True)),
        )
    except DatabaseError:
        logger.exception('Failed to read the mailbox quota allocation')
        return 0, 0, 0
    return totals['allocated'] or 0, totals['count'] or 0, totals['unlimited'] or 0


def _stored_and_unfilled() -> tuple[int | None, int | None]:
    """(bytes stored, bytes still promiseable) for quota-limited mailboxes.

    Dovecot's maildir layout is ``<root>/<domain>/<local_part>/``. For each
    finite mailbox: stored = its directory size, unfilled = max(0, quota −
    stored) — the room it can still grow into. Unlimited mailboxes are neither
    counted nor constrained. A mailbox whose directory is missing counts as
    empty (nothing stored yet). ``(None, None)`` when the mailbox list cannot
    be read from the database.
    """
    try:
        finite = list(
            Mailbox.objects.filter(quota_bytes__gt=0).values_list(
                'domain__name', 'local_part', 'quota_bytes'
            )
        )
    except DatabaseError:
        logger.exception('Failed to list quota-limited mailboxes')
        return None, None
    root = _MAIL_VHOSTS_DIR
    root_exists = os.path.isdir(root)
    stored_total = 0
    unfilled_total = 0
    for domain_name, local_part, quota in finite:
        stored = 0
        if root_exists:
            mailbox_root = os.path.join(root, domain_name, local_part)
            for dirpath, _dirnames, filenames in os.walk(mailbox_root):
                for name in filenames:
                    with suppress(OSError):
                        stored += os.path.getsize(os.path.join(dirpath, name))
        stored_total += stored
        unfilled_total += max(0, quota - stored)
    return stored_total, unfilled_total


class QuotaService:
    """Single interface for quota-budget reads (disk size + promised space)."""

    @staticmethod
    def get_budget() -> QuotaBudget:
        allocated, count, unlimited = _allocation()
        total, free = _disk_usage()
        stored, unfilled = _stored_and_unfilled()
        return QuotaBudget(
            disk_total_bytes=total,
            disk_free_bytes=free,
            allocated_bytes=allocated,
            mailbox_count=count,
            unlimited_count=unlimited,
            stored_bytes=stored,
            unfilled_bytes=unfilled,
        )


__all__ = ['QuotaService']
