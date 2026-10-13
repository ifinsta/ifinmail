"""DNS status viewset — GET endpoint (API flow)."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.platform.services.monitoring import MonitoringService
from backend.apps.core.serializers.health import DnsCheckV1, DnsStatusV1
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


def check_status(domain: str | None) -> DnsStatusV1:
    """The DNS records of one domain against public resolvers; changes nothing.

    A blank name means the configured mail domain. Raises ``ValueError`` (safe to show) when there
    is none. Unlike ``POST /domains/{name}/verify`` it does not store the outcome.
    """
    name = (domain or '').strip().lower() or primary_domain()
    if not name:
        raise ValueError('No mail domain is configured.')
    records = MonitoringService.check_dns(name)
    return DnsStatusV1(
        domain=name, records={key: DnsCheckV1(**value) for key, value in records.items()}
    )


__all__ = ['check_status', 'dns_status']
