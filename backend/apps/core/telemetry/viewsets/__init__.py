"""telemetry — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.telemetry.serializers import serialize_event, serialize_fingerprint
from backend.apps.core.telemetry.services.telemetry_service import TelemetryService
from backend.apps.core.telemetry.types import ErrorStatus

logger = logging.getLogger('backend.telemetry')

_PAGE_SIZE = 25


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
@require_GET
def telemetry_errors(request: HttpRequest) -> JsonResponse:
    """GET: paginated error events (?severity=&source=&q=&page=)."""
    result = TelemetryService.list_events(
        severity=request.GET.get('severity', '').strip().upper(),
        source=request.GET.get('source', '').strip().upper(),
        query=request.GET.get('q', '').strip(),
        page=int(request.GET.get('page', '1') or 1),
        page_size=_PAGE_SIZE,
    )
    return JsonResponse(
        {
            'results': [serialize_event(e) for e in result['results']],
            'page': result['page'],
            'num_pages': result['num_pages'],
            'total': result['total'],
        }
    )


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
@require_GET
def telemetry_stats(request: HttpRequest) -> JsonResponse:
    """GET: aggregate stats for dashboards."""
    return JsonResponse(TelemetryService.get_stats())


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
@require_GET
def telemetry_fingerprints(request: HttpRequest) -> JsonResponse:
    """GET: top fingerprints for grouping view."""
    rows = TelemetryService.list_fingerprints(limit=25)
    return JsonResponse({'results': [serialize_fingerprint(f) for f in rows]})


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
@require_POST
def telemetry_ack(request: HttpRequest) -> JsonResponse:
    """POST: {fingerprint, status} → ACKED/RESOLVED/MUTED."""
    fingerprint_hash = request.POST.get('fingerprint', '').strip()
    status = request.POST.get('status', ErrorStatus.ACKED.value).strip().upper()
    if not fingerprint_hash or status not in {s.value for s in ErrorStatus}:
        return JsonResponse(
            {'success': False, 'message': 'Invalid fingerprint or status'}, status=400
        )
    ok = TelemetryService.ack_fingerprint(fingerprint_hash, status)
    return JsonResponse({'success': ok}, status=200 if ok else 404)


__all__ = [
    'telemetry_ack',
    'telemetry_errors',
    'telemetry_fingerprints',
    'telemetry_stats',
]
