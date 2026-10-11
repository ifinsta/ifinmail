"""DNS status viewset — GET endpoint (API flow)."""

import os

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.dns.serializers import DNSStatusResponse
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.verification import DomainVerificationService
from backend.services.monitoring import MonitoringService


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_status(request: HttpRequest) -> JsonResponse:
    """GET endpoint: return current DNS record verification status."""
    domain = request.GET.get('domain', os.environ.get('DOMAIN', os.environ.get('MAIL_DOMAIN', '')))
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
