"""DNS configure viewset — POST endpoint (API flow)."""

import logging
import os

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.dns.serializers import (
    DNSConfigureRequest,
    DNSConfigureResponse,
    ProvisionStepOut,
)
from backend.apps.dns.services import PROVIDER_MAP, DNSService
from backend.apps.domains.services.provisioning import (
    DomainProvisioningError,
    ProvisioningService,
)

logger = logging.getLogger('backend')


@require_POST
@ensure_csrf_cookie
@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_configure(request: HttpRequest) -> JsonResponse:
    """POST endpoint: configure DNS records via the selected provider."""
    parsed = DNSConfigureRequest.from_post(request.POST, os.environ.get('DOMAIN', ''))

    if parsed.provider not in PROVIDER_MAP:
        response = DNSConfigureResponse(
            success=False, message=f'Unknown provider: {parsed.provider}'
        )
        return JsonResponse(response.to_dict(), status=400)

    cls, fields, _ = PROVIDER_MAP[parsed.provider]
    missing = parsed.missing_fields(list(fields))
    if missing:
        response = DNSConfigureResponse(
            success=False, message=f'Missing credentials: {", ".join(missing)}'
        )
        return JsonResponse(response.to_dict(), status=400)

    DNSService.update_or_create_config(
        provider_name=parsed.provider,
        credentials=parsed.credential_map(list(fields)),
    )

    # The pipeline creates the DKIM key first, then pushes records through the
    # provider that was just saved, so the DKIM record is never a placeholder.
    try:
        outcome = ProvisioningService.add_domain(
            parsed.domain,
            actor=request.user.email if request.user.is_authenticated else None,
        )
    except DomainProvisioningError as e:
        response = DNSConfigureResponse(success=False, message=str(e))
        return JsonResponse(response.to_dict(), status=400)
    except Exception:
        logger.exception('DNS configuration failed for %s via %s', parsed.domain, parsed.provider)
        response = DNSConfigureResponse(
            success=False, message='DNS configuration failed. See the server log.'
        )
        return JsonResponse(response.to_dict(), status=500)
    dns_step = next(st for st in outcome.steps if st.name == 'DNS records')
    success = str(dns_step.status) == 'ok'
    response = DNSConfigureResponse(
        success=success,
        message=dns_step.detail,
        records_created=(
            [f'{r["type"]} {r["name"]}' for r in outcome.dns_records] if success else []
        ),
        records_failed=[] if success else [dns_step.detail],
        steps=[
            ProvisionStepOut(name=st.name, status=str(st.status), detail=st.detail)
            for st in outcome.steps
        ],
    )
    return JsonResponse(response.to_dict())


__all__ = ['dns_configure']
