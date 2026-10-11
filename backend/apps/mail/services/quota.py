"""Space budget — how much mailbox quota the mail volume can still promise.

The budget compares the disk holding the mail volume against the sum of all
finite mailbox quotas. It never blocks an action: quotas are promises, and
deliberate overcommit is a valid admin choice — the console just makes the
numbers visible and warns when the promises exceed the disk.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

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
        totals: dict[str, Any] = Mailbox.objects.aggregate(
            allocated=Sum('quota_bytes'),
            count=Count('id'),
            unlimited=Count('id', filter=Q(quota_bytes=0) | Q(quota_bytes__isnull=True)),
        )
    except DatabaseError:
        logger.exception('Failed to read the mailbox quota allocation')
        return 0, 0, 0
    return totals['allocated'] or 0, totals['count'] or 0, totals['unlimited'] or 0


class QuotaService:
    """Single interface for quota-budget reads (disk size + promised space)."""

    @staticmethod
    def get_budget() -> QuotaBudget:
        allocated, count, unlimited = _allocation()
        total, free = _disk_usage()
        return QuotaBudget(
            disk_total_bytes=total,
            disk_free_bytes=free,
            allocated_bytes=allocated,
            mailbox_count=count,
            unlimited_count=unlimited,
        )


__all__ = ['QuotaService']
