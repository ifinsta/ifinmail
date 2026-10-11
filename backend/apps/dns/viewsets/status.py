"""DNS status viewset — GET endpoint (API flow)."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.platform.services.monitoring import MonitoringService
from backend.apps.dns.serializers import DNSStatusResponse
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.verification import DomainVerificationService
from backend.config.env import primary_domain

logger = logging.getLogger('backend')


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_status(request: HttpRequest) -> JsonResponse:
    """GET endpoint: return current DNS record verification status."""
    # A blank ``?domain=`` must not override the configured default: an empty
    # lookup would report every record as failed for a name that does not exist.
    domain = (request.GET.get('domain') or '').strip() or primary_domain()
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
    except Exception:
        # The detail goes to the server log; the response stays generic.
        logger.exception('DNS status check failed for %s', domain)
        response = DNSStatusResponse(domain=domain, error='DNS check failed')
        return JsonResponse(response.to_dict(), status=500)


__all__ = ['dns_status']
