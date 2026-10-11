"""Telemetry API views — JSON endpoints (API flow: web/api → services → models)."""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
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
    from backend.apps.core.telemetry.services.models import ErrorEvent

    severity = request.GET.get('severity', '').strip().upper()
    source = request.GET.get('source', '').strip().upper()
    query = request.GET.get('q', '').strip()
    try:
        qs = ErrorEvent.objects.select_related('fingerprint').order_by('-created_at')
        if severity:
            qs = qs.filter(severity=severity)
        if source:
            qs = qs.filter(source=source)
        if query:
            qs = qs.filter(message__icontains=query[:200])
        paginator = Paginator(qs, _PAGE_SIZE)
        page_num = max(int(request.GET.get('page', '1') or 1), 1)
        page = paginator.get_page(page_num)
        return JsonResponse(
            {
                'results': [serialize_event(e) for e in page.object_list],
                'page': page.number,
                'num_pages': paginator.num_pages,
                'total': paginator.count,
            }
        )
    except Exception as exc:
        logger.warning('telemetry_errors failed: %s', exc)
        # Graceful degradation — serve the memory buffer instead of 500.
        recent = TelemetryService.get_recent(25)
        return JsonResponse({'results': recent, 'page': 1, 'num_pages': 1, 'total': len(recent)})


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
    from backend.apps.core.telemetry.services.models import ErrorFingerprint

    try:
        rows = list(ErrorFingerprint.objects.order_by('-count')[:25])
        return JsonResponse({'results': [serialize_fingerprint(f) for f in rows]})
    except Exception as exc:
        logger.warning('telemetry_fingerprints failed: %s', exc)
        return JsonResponse({'results': []})


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
