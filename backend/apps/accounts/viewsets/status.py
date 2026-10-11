"""Service status viewset (monitoring bots, status pages). Scope: console.access."""

from __future__ import annotations

from ninja import Router

from backend.apps.accounts.serializers import StatusOut
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


__all__ = ['router']
