"""The unified logs report: one figure set across every log the console collects.

Nothing here reads a log file: the threat digest already reduced each source to a few counters per
hour (``threats.rollup``), so a day, a week or a month is a sum of small rows, whatever the traffic.
Detail (the audit trail, errors, findings) is read from the tables that keep it. The same dict
feeds the page, the JSON export, the weekly email and the assistant tool.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone

from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.telemetry.models import ErrorEvent, KnownPlace, ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import rollup
from backend.apps.core.telemetry.threats.types import Severity

PERIODS: dict[str, tuple[str, timedelta]] = {
    'day': ('Last 24 hours', timedelta(hours=24)),
    'week': ('Last 7 days', timedelta(days=7)),
    'month': ('Last 30 days', timedelta(days=30)),
}
# What each source keeps (the size caps are the rotation scripts', the days the compaction's).
SOURCES: tuple[tuple[str, str, str], ...] = (
    ('nginx', 'Web server', '16 MiB + rotated copy'),
    ('postfix', 'Postfix (mail transfer)', '16 MiB + rotated copy'),
    ('dovecot', 'Dovecot (mailboxes)', '16 MiB + rotated copy'),
    ('rspamd', 'Rspamd (spam filter)', '16 MiB + rotated copy'),
)
_QUIET_ACTIONS = ('login_success', 'logout', 'assistant_question')  # not "changes"
_SEVERITY_WORD = {int(s): s.word for s in Severity}


def _sum(rows: list[dict[str, Any]], source: str, key: str) -> int:
    return sum(int((r.get('sources', {}).get(source) or {}).get(key) or 0) for r in rows)


def _sum_dict(rows: list[dict[str, Any]], source: str, key: str) -> dict[str, int]:
    total: Counter[str] = Counter()
    for r in rows:
        total.update((r.get('sources', {}).get(source) or {}).get(key) or {})
    return dict(total)


def _age(last_at: str | None, now: datetime) -> tuple[int | None, str]:
    """Seconds since a source's newest line, and the same in words."""
    if not last_at:
        return None, 'never'
    try:
        seconds = max(int((now - datetime.fromisoformat(last_at)).total_seconds()), 0)
    except ValueError:
        return None, 'unknown'
    if seconds < 90:
        return seconds, f'{seconds} s ago'
    if seconds < 5400:
        return seconds, f'{seconds // 60} min ago'
    if seconds < 172800:
        return seconds, f'{seconds // 3600} h ago'
    return seconds, f'{seconds // 86400} days ago'


def sources_table(
    latest: dict[str, Any], now: datetime, chain: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Each source: is it alive, how busy, how long it is kept, and what needs attention."""
    data = latest.get('sources') or {}
    out: list[dict[str, Any]] = []
    for key, label, kept in SOURCES:
        src = data.get(key) or {}
        seconds, ago = _age(src.get('last_at'), now)
        limit = rollup.SILENT_AFTER[key].total_seconds()
        note = ''
        if not src.get('exists'):
            status, note = 'missing', 'Not collected yet: it appears after the next update.'
        elif seconds is not None and seconds > limit:
            status, note = 'silent', f'No line for {ago.replace(" ago", "")}.'
        elif src.get('dns_blocked'):
            status = 'attention'
            note = 'Blocklist lookups refused: ' + ', '.join(sorted(src['dns_blocked']))
        else:
            status = 'ok'
        out.append(
            {
                'key': key,
                'label': label,
                'status': status,
                'last': ago,
                'lines': int(src.get('lines') or 0),
                'kept': kept,
                'size': int(src.get('size') or 0),
                'note': note,
            }
        )
    verified = (chain or {}).get('ok')
    out.append(
        {
            'key': 'audit',
            'label': 'Audit trail',
            'status': 'ok' if verified in (True, None) else 'attention',
            'last': 'in the database',
            'lines': AuditEvent.objects.filter(time__gte=now - timedelta(hours=1)).count(),
            'kept': '365 days, hash-chained',
            'size': 0,
            'note': '' if verified in (True, None) else 'The chain does not verify.',
        }
    )
    out.append(
        {
            'key': 'errors',
            'label': 'Application errors',
            'status': 'ok',
            'last': 'in the database',
            'lines': ErrorEvent.objects.filter(created_at__gte=now - timedelta(hours=1)).count(),
            'kept': 'warnings 48 h, errors until resolved',
            'size': 0,
            'note': '',
        }
    )
    return out


def build(
    period: str = 'day', now: datetime | None = None, chain: dict[str, Any] | None = None
) -> dict[str, Any]:
    period = period if period in PERIODS else 'day'
    now = now or timezone.now()
    label, span = PERIODS[period]
    since = now - span

    digests = list(
        ThreatDigest.objects.filter(hour__gte=since.replace(minute=0, second=0, microsecond=0))
        .order_by('hour')
        .values('hour', 'summary')
    )
    rows = [d['summary'] or {} for d in digests]
    latest = rows[-1] if rows else {}

    by_status: Counter[str] = Counter()
    for r in rows:
        by_status.update(r.get('by_status') or {})
    slowest = max(
        ((r.get('sources', {}).get('nginx') or {}).get('slowest') or {} for r in rows),
        key=lambda s: s.get('seconds', 0),
        default={},
    )
    web = {
        'requests': sum(int(r.get('requests') or 0) for r in rows),
        'by_status': dict(sorted(by_status.items())),
        'refused': by_status.get('4xx', 0),
        'closed': _sum(rows, 'nginx', 'closed'),
        'server_errors': by_status.get('5xx', 0),
        'busiest_minute': max((int(r.get('peak_per_minute') or 0) for r in rows), default=0),
        'slowest': slowest or None,
    }
    mail = {
        key: _sum(rows, 'postfix', key)
        for key in (
            'received',
            'delivered',
            'sent',
            'deferred',
            'bounced',
            'relay_denied',
            'unknown_recipient',
        )
    }
    mail['spam'] = _sum_dict(rows, 'rspamd', 'actions')
    mail['logins'] = _sum(rows, 'dovecot', 'logins')

    findings = list(
        ThreatFinding.objects.filter(last_seen__gte=since).order_by('-severity', '-last_seen')
    )
    blocks = AuditEvent.objects.filter(
        time__gte=since, action__in=('network_auto_block', 'network_block')
    ).count()
    security = {
        'findings': len(findings),
        'open': sum(1 for f in findings if f.status != ThreatFinding.RESOLVED),
        'by_severity': dict(Counter(_SEVERITY_WORD.get(f.severity, 'info') for f in findings)),
        'top': [
            {
                'severity': _SEVERITY_WORD.get(f.severity, 'info'),
                'title': f.title,
                'subject': f.subject,
                'count': f.count,
                'status': f.status,
                'last_seen': f.last_seen.isoformat(timespec='minutes'),
            }
            for f in findings[:6]
        ],
        'blocks': blocks,
        'failed_console_signins': sum(int(r.get('auth_failures') or 0) for r in rows),
        'failed_mail_signins': sum(int(r.get('mail_failures') or 0) for r in rows),
        'new_places': ThreatFinding.objects.filter(kind='new_place', last_seen__gte=since).count(),
        'known_places': KnownPlace.objects.count(),
    }

    changes = [
        {
            'time': e.time.isoformat(timespec='minutes'),
            'when': e.time.astimezone(UTC).strftime('%m-%d %H:%M'),
            'user': e.user,
            'action': e.action,
            'detail': e.detail[:110],
            'severity': e.severity,
        }
        for e in AuditEvent.objects.filter(time__gte=since)
        .exclude(action__in=_QUIET_ACTIONS)
        .exclude(action__startswith='stepup')
        .order_by('-time')[:8]
    ]
    errors_qs = ErrorEvent.objects.filter(created_at__gte=since)
    errors = {
        'total': errors_qs.count(),
        'by_type': dict(
            Counter(
                errors_qs.exclude(severity__in=['DEBUG', 'INFO']).values_list('exc_type', flat=True)
            )
        ),
    }
    table = sources_table(latest, now, chain)
    needing = [s for s in table if s['status'] != 'ok']
    return {
        'period': period,
        'label': label,
        'since': since.astimezone(UTC).isoformat(timespec='minutes'),
        'until': now.astimezone(UTC).isoformat(timespec='minutes'),
        'hours_covered': len(rows),
        'hours_expected': int(span.total_seconds() // 3600),
        'web': web,
        'mail': mail,
        'security': security,
        'changes': changes,
        'errors': errors,
        'sources': table,
        'sources_ok': len(table) - len(needing),
        'sources_total': len(table),
        'attention': [s['label'] for s in needing],
        'events': web['requests']
        + sum(v for k, v in mail.items() if isinstance(v, int))
        + len(changes),
    }
