"""Core jobs: certificate expiry monitoring."""

from __future__ import annotations

import logging
import os

from celery import shared_task
from django.core.cache import cache
from django.core.mail import send_mail

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.platform.services.monitoring import MonitoringService

logger = logging.getLogger('backend')

_WARN_DAYS = 21
_EMAIL_DAYS = 14


@shared_task(name='core.check_certificate_expiry')
def check_certificate_expiry() -> dict[str, object]:
    """Record certificate status and warn the administrator before it expires."""
    result = MonitoringService.check_tls_expiry()
    days = result.get('days')
    if days is None:
        AuditService.record(
            action='certificate_check',
            detail=str(result.get('error', 'No certificate found')),
            severity='warn',
        )
        return result
    if days <= _WARN_DAYS:
        AuditService.record(
            action='certificate_expiring',
            detail=f'TLS certificate expires in {days} days',
            severity='warn' if days > 7 else 'err',
        )
    admin = os.environ.get('ADMIN_EMAIL', '').strip()
    if days <= _EMAIL_DAYS and admin and cache.add('cert-expiry-mail', 1, 24 * 3600):
        try:
            send_mail(
                'TLS certificate expires soon',
                f'The mail server certificate expires in {days} days. '
                'Check that port 80 is open and DNS points at this server so renewal can run.',
                None,
                [admin],
            )
        except Exception:
            logger.exception('Could not send the certificate expiry warning')
    return result
