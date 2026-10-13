"""dns — api.py: the DNS routes of the v1 API (urls.py → api.py → viewsets/ contract).

``GET /dns/status`` is a read-only check (scope ``dns.manage``). Recording a verification is
``POST /domains/{name}/verify``. The console's own page-driven calls (``dns_configure``,
``dns_status``, ``dns_verify_domain``: session and CSRF, used by its templates) are listed in
``backend/config/api_versions.py`` as console endpoints, not part of this contract.
"""

from ninja import Router

from backend.apps.accounts.viewsets.auth import ApiRequest, require_scope
from backend.apps.accounts.viewsets.errors import errors, problem
from backend.apps.core.serializers.health import DnsStatusV1

from .viewsets import dns_configure, dns_status, dns_verify_domain
from .viewsets.status import check_status

router = Router(tags=['dns'])


@router.get('/dns/status', response={200: DnsStatusV1, **errors(422)}, summary='DNS record status')
@require_scope('dns.manage')
def api_dns_status(request: ApiRequest, domain: str | None = None) -> DnsStatusV1:
    """Check one domain's MX, SPF, DKIM and DMARC records. Defaults to the mail domain."""
    try:
        return check_status(domain)
    except ValueError as exc:
        raise problem(exc) from exc


__all__ = ['dns_configure', 'dns_status', 'dns_verify_domain', 'router']
