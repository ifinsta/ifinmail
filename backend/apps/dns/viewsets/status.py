"""DNS status viewset — GET endpoint (API flow)."""

import os

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.platform.services.monitoring import MonitoringService
from backend.apps.dns.serializers import DNSStatusResponse
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.verification import DomainVerificationService


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_status(request: HttpRequest) -> JsonResponse:
    """GET endpoint: return current DNS record verification status."""
    # A blank ``?domain=`` must not override the configured default: an empty
    # lookup would report every record as failed for a name that does not exist.
    domain = (request.GET.get('domain') or '').strip()
    if not domain:
        domain = os.environ.get('DOMAIN') or os.environ.get('MAIL_DOMAIN') or ''
    if not domain:
        response = DNSStatusResponse(domain='', error='No mail domain configured')
        return JsonResponse(response.to_dict(), status=400)
    try:
        row = DomainService.get_domain_by_name(domain)
        # Persist the outcome for hosted domains so the dashboard reflects it.
        status = (
            DomainVerificationService.verify(row).as_dict()
            if row is not None
            else MonitoringService.check_dns(domain)
        )
        return JsonResponse(DNSStatusResponse(domain=domain, records=status).to_dict())
    except Exception as e:
        return JsonResponse(DNSStatusResponse(domain=domain, error=str(e)).to_dict(), status=500)


__all__ = ['dns_status']
