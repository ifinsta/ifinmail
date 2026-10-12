"""Logs view — system logs and audit trail."""

import csv
import json
import logging
from collections.abc import Iterator

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from backend.apps.core.platform.services.audit import AuditService

from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')

_AUDIT_PAGE_SIZE = 20


def _admin_log_rows(level: str = '') -> list[dict[str, str]]:
    """Return audit + telemetry error events for the logs table."""
    events = AuditService.get_recent(50)
    rows = []
    for e in reversed(events):
        severity = e.get('severity', 'info')
        if level and severity.lower() != level.lower():
            continue
        rows.append(
            {
                'timestamp': e.get('time', '').replace('T', ' ')[:19] if e.get('time') else '',
                'level': severity.upper(),
                'service': e.get('action', 'system'),
                'message': e.get('detail', '') or e.get('action', ''),
            }
        )
    # Merge persisted error telemetry (DB first, memory fallback) so real
    # errors replace the "telemetry not yet integrated" placeholder.
    try:
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

        for e in TelemetryService.get_recent(50):
            severity = e.get('severity', 'ERROR')
            if level and severity.lower() != level.lower():
                continue
            rows.append(
                {
                    'timestamp': e.get('time', '').replace('T', ' ')[:19] if e.get('time') else '',
                    'level': severity.upper(),
                    'service': e.get('service', 'telemetry'),
                    'message': e.get('detail', '') or e.get('action', ''),
                }
            )
    except Exception as exc:
        logger.warning('Telemetry merge for logs page failed: %s', exc)
    # Newest-first by timestamp string (ISO-derived) — stable without parsing.
    rows.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
    return rows[:100]


def _admin_audit_items(page: int = 1, level: str = '') -> list[dict[str, str]]:
    """Return paginated audit trail items."""
    events = AuditService.get_recent(200)
    items = []
    for e in reversed(events):
        severity = e.get('severity', 'info')
        if level and severity.lower() != level.lower():
            continue
        items.append(
            {
                'type': severity.upper(),
                'title': e.get('action', 'Event'),
                'body': e.get('detail', ''),
                'actor': e.get('user', 'system'),
                'age': e.get('time', '').replace('T', ' ')[:19] if e.get('time') else '',
            }
        )
    paginator = Paginator(items, _AUDIT_PAGE_SIZE)
    try:
        page_num = min(max(int(page), 1), paginator.num_pages)
    except (ValueError, TypeError):
        page_num = 1
    return list(paginator.get_page(page_num).object_list)


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs(request: HttpRequest) -> HttpResponse:
    """System logs and audit trail screen."""
    level = request.GET.get('level', '').strip().upper()
    page = request.GET.get('page', '1')
    try:
        page_num = int(page)
    except (ValueError, TypeError):
        page_num = 1

    log_rows = _admin_log_rows(level=level)
    audit_items = _admin_audit_items(page=page_num, level=level)
    try:
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

        telemetry_stats = TelemetryService.get_stats()
    except Exception:
        telemetry_stats = {}
    is_mock = len(log_rows) == 0 and len(audit_items) == 0

    return render(
        request,
        'admin/logs.html',
        {
            'active_section': 'logs',
            'header_search_placeholder': 'Search system logs...',
            'log_headers': [_('Timestamp'), _('Level'), _('Service'), _('Message')],
            'log_rows': log_rows,
            'log_empty_message': _('No log data available — telemetry not yet integrated'),
            'audit_items': audit_items,
            'is_mock': is_mock,
            'telemetry_stats': telemetry_stats,
            'current_level': level,
            'current_page': page_num,
            'has_more': len(audit_items) >= _AUDIT_PAGE_SIZE,
        },
    )


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs_export(request: HttpRequest) -> HttpResponse:
    """Export the retained audit trail as CSV (default) or JSONL (``?format=jsonl``).

    Both read the database, not the per-process memory buffer. JSONL carries the
    sequence number and hash link of each event, and ``X-Audit-Head`` holds the
    newest ``seq:hash`` so it can be recorded off-host to detect later truncation.
    """
    level = request.GET.get('level', '').strip().upper()
    fmt = request.GET.get('format', 'csv').strip().lower()
    rows = AuditService.export_rows(severity=level)

    if fmt == 'jsonl':
        head = AuditService.verify_chain()

        def lines() -> Iterator[str]:
            for row in rows:
                yield json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n'

        response = StreamingHttpResponse(lines(), content_type='application/x-ndjson')
        response['Content-Disposition'] = 'attachment; filename=audit_log.jsonl'
        response['X-Audit-Head'] = f'{head["head_seq"] or 0}:{head["head_hash"]}'
        response['X-Audit-Chain'] = 'ok' if head['ok'] else 'broken'
        return response

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename=audit_log.csv'
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'Level', 'Service/Action', 'Message', 'User'])
    for e in rows:
        writer.writerow(
            [
                e['time'].replace('T', ' ')[:19],
                e['severity'].upper(),
                e['action'],
                e['detail'],
                e['user'] or 'system',
            ]
        )
    return response


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs_live_data(request: HttpRequest) -> JsonResponse:
    """Return the latest log entries as JSON for polling-based live view."""
    level = request.GET.get('level', '').strip().upper()
    rows = _admin_log_rows(level=level)
    # Return only the most recent 10 entries for polling efficiency
    return JsonResponse(
        {'rows': rows[-10:] if len(rows) > 10 else rows},
        content_type='application/json; charset=utf-8',
    )


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs_full_history(request: HttpRequest) -> HttpResponse:
    """Paginated full audit history page."""
    return logs(request)
