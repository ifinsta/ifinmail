"""Domain jobs: DNS verification, DKIM key files and the certificate host list."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.services.certificates import CertificateService

from .services.dkim import DKIMService
from .services.verification import DomainVerificationService

logger = logging.getLogger('backend')


@shared_task(name='domains.verify_all')
def verify_all_domains() -> dict[str, bool]:
    """Re-check DNS for every hosted domain and store the outcome."""
    results = DomainVerificationService.verify_all()
    return {name: result.accepts_mail for name, result in results.items()}


@shared_task(name='domains.sync_dkim_files')
def sync_dkim_files() -> int:
    """Write any DKIM key that exists in the database but not on disk (e.g. a fresh volume)."""
    return DKIMService.sync_files()


@shared_task(name='domains.sync_certificate_hosts')
def sync_certificate_hosts() -> int:
    """Refresh the list of hostnames the certbot container should keep covered."""
    return len(CertificateService.sync())
