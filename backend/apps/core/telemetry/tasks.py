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


@shared_task(name='telemetry.threat_digest')
def threat_digest() -> dict[str, Any]:
    """Read the access log and sign-in record, keep the slim version, tell someone if it matters."""
    from backend.apps.core.telemetry.threats import autoblock, digest

    if not digest.enabled():
        return {'enabled': False}
    result = digest.run()
    acted = autoblock.run()
    return {
        'requests': result.summary.requests,
        'findings': len(result.findings),
        'log': result.log_available,
        'alerted': result.alerted,
        'summarised': result.summarised,
        'blocked': acted.blocked,
        'flood_mode': acted.flood_started,
    }


@shared_task(name='telemetry.threat_compact')
def threat_compact() -> dict[str, int]:
    """Discard telemetry the digests have already summarised."""
    from backend.apps.core.telemetry.threats import digest

    return digest.compact()


@shared_task(name='telemetry.digest')
def error_digest() -> dict[str, Any]:
    """Summarise last-24h errors; returns payload (mail hookup is optional)."""
    from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

    stats = TelemetryService.get_stats()
    admin = os.environ.get('ADMIN_EMAIL', '').strip()
    if admin and stats.get('open_critical_24h', 0) > 0:
        try:
            from django.core.mail import send_mail

            from backend.config.branding import brand_name

            send_mail(
                f'[{brand_name()}] {stats["open_critical_24h"]} errors in last 24h',
                f'Total events: {stats["total_24h"]}\nTop: {stats["top"]}',
                None,
                [admin],
                fail_silently=True,
            )
        except Exception as exc:
            logger.warning('Telemetry digest mail failed: %s', exc)
    return stats
