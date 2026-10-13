"""Core jobs: certificate expiry monitoring, audit-trail maintenance."""

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


@shared_task(name='core.reconcile_entrypoints')
def reconcile_entrypoints() -> dict[str, object]:
    """Keep the firewall's rule file equal to what the console intends (every few minutes)."""
    from backend.apps.core.platform.services.entrypoints import EntryPointService

    lapsed = EntryPointService.expire()
    for cidr in lapsed:
        AuditService.record(action='network_unblock', user='system', detail=f'{cidr} (time was up)')
    flood_ended = EntryPointService.expire_flood()
    if flood_ended:
        AuditService.record(action='flood_mode_off', user='system', detail='flood mode ended')
    wrote = EntryPointService.reconcile() or bool(lapsed) or flood_ended
    if wrote:
        AuditService.record(
            action='firewall_published',
            user='system',
            detail=', '.join(f'{k}={v}' for k, v in EntryPointService.summary().items()),
        )
    return {'wrote': wrote, 'lapsed': lapsed, **EntryPointService.summary()}


@shared_task(name='core.check_for_updates')
def check_for_updates() -> dict[str, object]:
    """Every six hours: is a newer ifinmail release published? (off when disabled)."""
    from backend.apps.core.platform.services.updates import UpdateService

    status = UpdateService.check()
    return {'current': status.current, 'latest': status.latest, 'available': status.available}


@shared_task(name='core.audit_maintenance')
def audit_maintenance() -> dict[str, object]:
    """Apply audit retention, then verify the hash chain and raise an alarm if it is broken."""
    deleted, before = AuditService.purge_expired()
    chain = AuditService.verify_chain()
    if not chain['ok']:
        error = chain['error'] or {}
        AuditService.record(
            action='audit_chain_broken',
            detail=(
                f'Audit trail fails verification at seq {error.get("seq")} ({error.get("reason")})'
            ),
            severity='err',
        )
        logger.error('Audit chain broken: %s', error)
    return {'deleted': deleted, 'before': before, **chain}
