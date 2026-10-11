"""Telemetry background jobs — retention purge + daily digest."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('backend.telemetry')


@shared_task(name='telemetry.purge')
def purge_old_errors() -> dict[str, Any]:
    """Delete ErrorEvents older than the retention window (default 30d)."""
    from backend.apps.core.telemetry.services.models import ErrorEvent

    try:
        days = int(os.environ.get('TELEMETRY_RETENTION_DAYS', '30'))
    except ValueError:
        days = 30
    cutoff = timezone.now() - timedelta(days=days)
    try:
        deleted, _ = ErrorEvent.objects.filter(created_at__lt=cutoff).delete()
        return {'deleted': deleted, 'cutoff': cutoff.isoformat(), 'retention_days': days}
    except Exception as exc:
        logger.warning('Telemetry purge failed: %s', exc)
        return {'deleted': 0, 'error': str(exc)}


@shared_task(name='telemetry.digest')
def error_digest() -> dict[str, Any]:
    """Summarise last-24h errors; returns payload (mail hookup is optional)."""
    from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

    stats = TelemetryService.get_stats()
    admin = os.environ.get('ADMIN_EMAIL', '').strip()
    if admin and stats.get('open_critical_24h', 0) > 0:
        try:
            from django.core.mail import send_mail

            send_mail(
                f'[ifinmail] {stats["open_critical_24h"]} errors in last 24h',
                f'Total events: {stats["total_24h"]}\nTop: {stats["top"]}',
                None,
                [admin],
                fail_silently=True,
            )
        except Exception as exc:
            logger.warning('Telemetry digest mail failed: %s', exc)
    return stats
