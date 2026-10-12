"""Service status viewset (monitoring bots, status pages). Scope: console.access."""

from __future__ import annotations

from django.http import HttpResponse
from ninja import Router

from backend.apps.accounts.serializers import StatusOut
from backend.apps.accounts.services import metrics
from backend.apps.accounts.viewsets.auth import require_scope
from backend.apps.domains.services import DomainService
from backend.apps.mail.services import MailService

router = Router(tags=['status'])


@router.get('/status', response=StatusOut)
@require_scope('console.access')
def status_detail(request) -> StatusOut:
    """Counts only — enough for monitoring, no message bodies, no secrets."""
    return StatusOut(
        ok=True,
        domains=DomainService.get_domain_count(),
        mailboxes=MailService.get_mailbox_count(),
    )


@router.get('/metrics', response={200: None})
@require_scope('audit.view')
def metrics_text(request) -> HttpResponse:
    """Prometheus text format for any scraper. Scope: audit.view (read-only)."""
    return HttpResponse(metrics.render(), content_type='text/plain; version=0.0.4; charset=utf-8')


__all__ = ['router']
