"""Logs view: the audit trail and application errors, filterable, paginated, exportable."""

import csv
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone

from backend.apps.core.platform.services.audit import AuditService

from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')

PAGE_SIZE = 25
LIVE_LIMIT = 50
LEVELS = (('', 'All levels'), ('error', 'Errors'), ('warning', 'Warnings'), ('info', 'Information'))
PERIODS = (
    ('hour', 'Last hour', timedelta(hours=1)),
    ('day', 'Last 24 hours', timedelta(hours=24)),
    ('week', 'Last 7 days', timedelta(days=7)),
    ('month', 'Last 30 days', timedelta(days=30)),
    ('all', 'Everything retained', None),
)
TABS = ('activity', 'errors')
_CHAIN_CACHE_KEY = 'logs:audit-chain'
_CHAIN_CACHE_SECONDS = 1800  # the walk reads every retained event: do it rarely
_LEVEL_WORDS = {'error': 'Error', 'warning': 'Warning', 'info': 'Info'}


def _filters(request: HttpRequest) -> dict:
    """The filters in the query string, normalised (anything unknown means "no filter")."""
    level = request.GET.get('level', '').strip().lower()
    if level not in ('error', 'warning', 'info'):
        level = ''
    period = request.GET.get('period', 'all').strip().lower()
    if period not in {key for key, _, _ in PERIODS}:
        period = 'all'
    tab = request.GET.get('tab', 'activity').strip().lower()
    try:
        page = max(int(request.GET.get('page', '1')), 1)
    except (TypeError, ValueError):
        page = 1
    tab = tab if tab in TABS else 'activity'
    if tab == 'errors':
        period = 'all'  # application errors are paged by the telemetry store, not by period
    return {
        'tab': tab,
        'level': level,
        'period': period,
        'q': request.GET.get('q', '').strip()[:100],
        'page': page,
    }


def _since(period: str) -> datetime | None:
    span = next((delta for key, _, delta in PERIODS if key == period), None)
    return timezone.now() - span if span else None


def _when(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _shape(row: dict) -> dict:
    when = _when(row.get('time', ''))
    level = row.get('level') or AuditService.level_of(row.get('severity', ''))
    return {
        'id': row.get('id', ''),
        'when': when,
        'time': when.strftime('%Y-%m-%d %H:%M:%S') if when else '',
        'time_iso': row.get('time', ''),
        'level': level,
        'level_word': _LEVEL_WORDS.get(level, 'Info'),
        'action': row.get('action', ''),
        'user': row.get('user') or 'system',
        'detail': row.get('detail', ''),
    }


def _query(filters: dict, *, exclude: tuple[str, ...] = ('tab', 'page')) -> str:
    defaults = {'period': 'all'}  # the default is not worth a place in every link
    return urlencode(
        {k: v for k, v in filters.items() if v and k not in exclude and defaults.get(k) != v}
    )


def _page_links(page: int, pages: int) -> list[int | None]:
    """Page numbers to show, ``None`` standing for a gap."""
    wanted = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    out: list[int | None] = []
    for number in wanted:
        if out and isinstance(out[-1], int) and number - out[-1] > 1:
            out.append(None)
        out.append(number)
    return out


def _chain() -> dict:
    """Integrity of the audit hash chain, re-walked at most every half hour."""
    cached = cache.get(_CHAIN_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        result = AuditService.verify_chain()
        status = {
            'ok': bool(result['ok']),
            'checked': result['checked'],
            'bad_seq': (result.get('error') or {}).get('seq'),
            'checked_at': timezone.now(),
        }
    except Exception as exc:
        logger.warning('Audit chain verification failed: %s', exc)
        status = {'ok': None, 'checked': 0, 'bad_seq': None, 'checked_at': timezone.now()}
    cache.set(_CHAIN_CACHE_KEY, status, _CHAIN_CACHE_SECONDS)
    return status


def _errors_tab(filters: dict) -> dict:
    from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

    severity = {'error': 'ERROR', 'warning': 'WARNING', 'info': 'INFO'}.get(filters['level'], '')
    listing = TelemetryService.list_events(
        severity=severity, query=filters['q'], page=filters['page'], page_size=PAGE_SIZE
    )
    rows = []
    for event in listing['results']:
        shaped = _shape({**event, 'level': AuditService.level_of(event.get('severity', ''))})
        shaped['where'] = event.get('service', '')
        shaped['correlation'] = event.get('correlation_id', '')
        rows.append(shaped)
    return {
        'rows': rows,
        'total': listing['total'],
        'page': listing['page'],
        'pages': listing['num_pages'],
        'top': TelemetryService.list_fingerprints(limit=5),
    }


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs(request: HttpRequest) -> HttpResponse:
    """The logs screen: Activity (audit trail) and Errors (application errors)."""
    filters = _filters(request)
    since = _since(filters['period'])
    activity = AuditService.search(
        level=filters['level'],
        q=filters['q'],
        since=since,
        page=filters['page'],
        page_size=PAGE_SIZE,
    )
    rows = [_shape(row) for row in activity['rows']]
    counts = AuditService.level_counts(since)
    errors = _errors_tab(filters) if filters['tab'] == 'errors' else None
    current = errors if errors is not None else {**activity, 'rows': rows}
    page, pages, total = current['page'], current['pages'], current['total']
    first = (page - 1) * PAGE_SIZE + 1 if total else 0
    try:
        from backend.apps.core.telemetry.services.telemetry_service import TelemetryService

        error_total = TelemetryService.get_stats().get('total_24h', 0)
    except Exception:
        error_total = 0
    chain = _chain()
    return render(
        request,
        'admin/logs.html',
        {
            'active_section': 'logs',
            'filters': filters,
            'filters_active': bool(filters['level'] or filters['q'] or filters['period'] != 'all'),
            'levels': LEVELS,
            'periods': [(key, label) for key, label, _ in PERIODS],
            'tab': filters['tab'],
            'rows': current['rows'],
            'errors': errors,
            'total': total,
            'page': page,
            'pages': pages,
            'first': first,
            'last': first + len(current['rows']) - 1 if current['rows'] else 0,
            'page_links': _page_links(page, pages),
            'base_query': _query(filters),
            'tab_query': _query(filters, exclude=('tab', 'page', 'level')),
            'export_query': _query(filters, exclude=('tab', 'page')),
            'counts': counts,
            'count_total': sum(counts.values()),
            'error_total_24h': error_total,
            'chain': chain,
            'retention_days': AuditService.retention_days(),
            'can_live': filters['tab'] == 'activity' and page == 1,
            'newest_iso': rows[0]['time_iso'] if rows else '',
        },
    )


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs_export(request: HttpRequest) -> HttpResponse:
    """Export the retained audit trail as CSV (default) or JSONL (``?format=jsonl``).

    Both read the database, not the per-process memory buffer, and honour the page's filters
    (``level``, ``q``, ``period``). JSONL carries the sequence number and hash link of each
    event, and ``X-Audit-Head`` holds the newest ``seq:hash`` so it can be recorded off-host to
    detect later truncation.
    """
    filters = _filters(request)
    fmt = request.GET.get('format', 'csv').strip().lower()
    rows = AuditService.export_rows(
        severity=filters['level'], q=filters['q'], since=_since(filters['period'])
    )

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
    """Events newer than ``after`` (an ISO time from the page), oldest first, for live view."""
    filters = _filters(request)
    after = _when(request.GET.get('after', ''))
    result = AuditService.search(
        level=filters['level'],
        q=filters['q'],
        since=_since(filters['period']),
        after=after,
        page=1,
        page_size=LIVE_LIMIT,
    )
    shaped = [_shape(row) for row in result['rows']]
    items = [
        {
            'id': r['id'],
            'time': r['time'],
            'time_iso': r['time_iso'],
            'level': r['level'],
            'level_word': r['level_word'],
            'action': r['action'],
            'user': r['user'],
            'detail': r['detail'],
        }
        for r in reversed(shaped)
    ]
    return JsonResponse(
        {'rows': items, 'total': result['total'], 'latest': shaped[0]['time_iso'] if shaped else ''}
    )


@login_required
@require_perm(PermissionCode.AUDIT_VIEW)
def logs_full_history(request: HttpRequest) -> HttpResponse:
    """The old "full history" address: the logs screen itself pages through everything now."""
    return logs(request)
