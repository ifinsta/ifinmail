"""DNS verify viewset — POST endpoint (API flow).

Re-checks one registered domain's DNS records on demand and stores the outcome,
the same work the periodic ``domains.verify_all`` job does.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.verification import DomainVerificationService

logger = logging.getLogger('backend')


def _json(payload: dict[str, object], status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status, content_type='application/json; charset=utf-8')


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
@require_POST
def dns_verify_domain(request: HttpRequest) -> JsonResponse:
    """POST endpoint: verify one registered domain now."""
    name = (request.POST.get('domain') or '').strip().lower()
    row = DomainService.get_domain_by_name(name) if name else None
    if row is None:
        return _json({'status': 'err', 'error': 'Unknown domain'}, status=404)
    try:
        result = DomainVerificationService.verify(row)
    except Exception:
        logger.exception('On-demand verification failed for %s', name)
        return _json({'status': 'err', 'error': 'Verification failed'}, status=500)
    AuditService.record(
        action='domain_verified',
        user=request.user.email if request.user.is_authenticated else None,
        detail=f'{name}: accepts_mail={result.accepts_mail}',
    )
    return _json(
        {
            'status': 'ok',
            'domain': name,
            'records': result.as_dict(),
            'accepts_mail': result.accepts_mail,
        }
    )


__all__ = ['dns_verify_domain']
