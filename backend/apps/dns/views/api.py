"""DNS API views — JSON endpoints (API flow)."""

import logging
import os

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.dns.services import PROVIDER_MAP, DNSService
from backend.apps.domains.models import Domain
from backend.apps.domains.services.provisioning import (
    DomainProvisioningError,
    ProvisioningService,
)
from backend.apps.domains.services.verification import DomainVerificationService
from backend.services.monitoring import MonitoringService

logger = logging.getLogger('backend')


@require_POST
@ensure_csrf_cookie
@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_configure(request: HttpRequest) -> JsonResponse:
    """POST endpoint: configure DNS records via the selected provider."""
    provider_name = request.POST.get('provider', '').lower()
    domain = request.POST.get('domain', os.environ.get('DOMAIN', ''))

    if provider_name not in PROVIDER_MAP:
        return JsonResponse(
            {'success': False, 'message': f'Unknown provider: {provider_name}'}, status=400
        )

    cls, fields, _ = PROVIDER_MAP[provider_name]
    creds = {f: request.POST.get(f, '').strip() for f in fields}
    if not all(creds.values()):
        missing = [f for f, v in creds.items() if not v.strip()]
        return JsonResponse(
            {'success': False, 'message': f'Missing credentials: {", ".join(missing)}'}, status=400
        )

    DNSService.update_or_create_config(
        provider_name=provider_name,
        credentials=creds,
    )

    # The pipeline creates the DKIM key first, then pushes records through the
    # provider that was just saved, so the DKIM record is never a placeholder.
    try:
        outcome = ProvisioningService.add_domain(
            domain,
            actor=request.user.email if request.user.is_authenticated else None,
        )
    except DomainProvisioningError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception:
        logger.exception('DNS configuration failed for %s via %s', domain, provider_name)
        return JsonResponse(
            {'success': False, 'message': 'DNS configuration failed. See the server log.'},
            status=500,
        )
    dns_step = next(st for st in outcome.steps if st.name == 'DNS records')
    success = str(dns_step.status) == 'ok'
    return JsonResponse(
        {
            'success': success,
            'message': dns_step.detail,
            'records_created': [f'{r["type"]} {r["name"]}' for r in outcome.dns_records]
            if success
            else [],
            'records_failed': [] if success else [dns_step.detail],
            'steps': [
                {'name': st.name, 'status': str(st.status), 'detail': st.detail}
                for st in outcome.steps
            ],
            'propagation_note': (
                'DNS changes may take up to 48 hours to propagate. '
                'The server re-checks automatically and starts accepting mail once MX resolves.'
            ),
        }
    )


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_status(request: HttpRequest) -> JsonResponse:
    """GET endpoint: return current DNS record verification status."""
    domain = request.GET.get('domain', os.environ.get('DOMAIN', os.environ.get('MAIL_DOMAIN', '')))
    try:
        row = Domain.objects.filter(name=domain).first()
        # Persist the outcome for hosted domains so the dashboard reflects it.
        status = (
            DomainVerificationService.verify(row).as_dict()
            if row is not None
            else MonitoringService.check_dns(domain)
        )
        return JsonResponse({'domain': domain, 'records': status})
    except Exception as e:
        return JsonResponse({'domain': domain, 'error': str(e)}, status=500)
