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


@shared_task(name='telemetry.geo_refresh')
def geo_refresh() -> dict[str, Any]:
    """Install or renew the country and operator data (about monthly; a no-op while it is fresh)."""
    from backend.apps.core.platform.services.audit import AuditService
    from backend.apps.core.telemetry.threats import geo

    result = geo.refresh_if_due()
    if result.get('ok') and not result.get('skipped'):
        AuditService.record(
            action='geo_data_updated',
            user='system',
            detail=f'{result.get("version")}: {result.get("rows")} ranges',
        )
    return result


@shared_task(name='telemetry.weekly_report')
def weekly_report() -> dict[str, Any]:
    """Email the week's report to the administrators (``LOG_REPORT_EMAIL=0`` turns it off)."""
    import os

    from django.core.mail import send_mail

    from backend.apps.core.telemetry import report

    if os.environ.get('LOG_REPORT_EMAIL', '1').lower() in ('0', 'false', 'no'):
        return {'sent': 0, 'disabled': True}
    from backend.apps.mail.services import containment

    recipients = containment._recipients_of_alerts(())  # noqa: SLF001
    if not recipients:
        return {'sent': 0, 'recipients': 0}
    data = report.build('week')
    host = os.environ.get('MAIL_HOSTNAME', '')
    link = f'https://{host}/accounts/logs/report/?period=week' if host else ''
    subject = 'ifinmail weekly report' + (
        f': {data["sources_total"] - data["sources_ok"]} log source(s) need attention'
        if data['attention']
        else ''
    )
    try:
        send_mail(subject, report.as_text(data, link), None, recipients, fail_silently=False)
    except Exception:
        logger.exception('Could not email the weekly report')
        return {'sent': 0, 'error': True}
    return {'sent': len(recipients)}


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
