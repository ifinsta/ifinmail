"""One hourly figure set per log source: the unified report's data, and the silence detector.

The digest already reads each source once per pass. This module turns what it read into a few
counters per source (never an address, a subject or a message), stored with the hour's summary, so
the report over a day, a week or a month is a sum of small rows rather than a re-read of the logs.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from . import access_log, delivery
from .access_log import ReadResult
from .mail_log import SourceStats
from .types import Action, Finding, MailEvent, Severity

# How long a source may say nothing before that is itself a finding. The web server logs its own
# health check every 30 s, so a few minutes of silence there means it stopped; mail logs are
# allowed to be quiet on a quiet server, so those thresholds are generous.
SILENT_AFTER = {
    'nginx': timedelta(minutes=30),
    'postfix': timedelta(hours=6),
    'rspamd': timedelta(hours=12),
    'dovecot': timedelta(hours=48),
}
BLOCKED_DNS_MIN = 3  # refused lookups of one blocklist in a window that make it a finding
_HASHY = re.compile(r'[0-9a-fA-F]{8,}|[0-9]{4,}')


def _page(path: str) -> str:
    """A path reduced to its first two segments, with ids folded: enough to say which page."""
    parts = [p for p in path.split('?')[0].split('/') if p][:2]
    return '/' + '/'.join(_HASHY.sub('…', p)[:40] for p in parts) + ('/' if parts else '')


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec='seconds') if value else None


def build(
    log: ReadResult, mail: list[MailEvent], stats: dict[str, SourceStats]
) -> dict[str, dict[str, Any]]:
    """Counters per source for the window just read."""
    out: dict[str, dict[str, Any]] = {}

    classes = Counter(f'{r.status // 100}xx' for r in log.requests if 100 <= r.status < 600)
    slowest = max(log.requests, key=lambda r: r.seconds, default=None)
    try:
        last = datetime.fromtimestamp(access_log.log_path().stat().st_mtime, UTC)
    except OSError:
        last = None
    out['nginx'] = {
        'exists': log.available,
        'lines': len(log.requests),
        'last_at': _iso(last),
        'by_status': dict(sorted(classes.items())),
        'refused': classes.get('4xx', 0),
        'closed': sum(1 for r in log.requests if r.status == 444),
        'slowest': {'page': _page(slowest.path), 'seconds': round(slowest.seconds, 2)}
        if slowest and slowest.seconds >= 0.5
        else None,
    }

    kinds = Counter((e.service, e.kind) for e in mail)
    postfix_kinds = (
        'received',
        'delivered',
        'sent',
        'deferred',
        'bounced',
        'relay_denied',
        'unknown_recipient',
        'auth_failed',
    )
    out['postfix'] = {
        **_file(stats.get('postfix')),
        **{
            k: sum(e.weight for e in mail if e.service == 'postfix' and e.kind == k)
            for k in postfix_kinds
        },
        'delivery': delivery.aggregate(mail),
    }
    out['dovecot'] = {
        **_file(stats.get('dovecot')),
        'logins': kinds[('dovecot', 'login_success')],
        'auth_failed': sum(
            e.weight for e in mail if e.service == 'dovecot' and e.kind == 'auth_failed'
        ),
    }
    actions = {
        k.removeprefix('spam_'): n
        for (svc, k), n in kinds.items()
        if svc == 'rspamd' and k.startswith('spam_')
    }
    blocked = Counter(e.who for e in mail if e.kind == 'dns_blocked')
    out['rspamd'] = {
        **_file(stats.get('rspamd')),
        'actions': dict(sorted(actions.items())),
        'dns_blocked': dict(blocked.most_common(5)),
    }
    return out


def _file(stat: SourceStats | None) -> dict[str, Any]:
    stat = stat or SourceStats()
    return {
        'exists': stat.exists,
        'lines': stat.lines,
        'last_at': _iso(stat.last_at),
        'size': stat.size,
    }


def findings(sources: dict[str, dict[str, Any]], now: datetime) -> list[Finding]:
    """A source that went quiet, and a blocklist that refuses this server's lookups."""
    found: list[Finding] = []
    health = Action('Check server health', 'health', 'See which service is failing and why.')
    for name, limit in SILENT_AFTER.items():
        data = sources.get(name) or {}
        if not data.get('exists') or not data.get('last_at'):
            continue
        try:
            last = datetime.fromisoformat(str(data['last_at']))
        except ValueError:
            continue
        if now - last <= limit:
            continue
        hours = (now - last).total_seconds() / 3600
        found.append(
            Finding(
                key=f'log_silent:{name}',
                kind='log_silent',
                severity=Severity.MEDIUM,
                subject=name,
                title='A log has gone quiet',
                summary=(
                    f'The {name} log has not had a line for {hours:.1f} hours (a healthy one '
                    f'writes at least every {int(limit.total_seconds() // 60)} minutes). '
                    'Either the service stopped or it is no longer logging; what it does would '
                    'then be invisible here.'
                ),
                count=1,
                first_seen=last,
                last_seen=now,
                tighten=[health],
            )
        )
    for zone, count in ((sources.get('rspamd') or {}).get('dns_blocked') or {}).items():
        if int(count) < BLOCKED_DNS_MIN:
            continue
        found.append(
            Finding(
                key=f'resolver_blocked:{zone}',
                kind='resolver_blocked',
                severity=Severity.MEDIUM,
                subject=zone,
                title='A spam blocklist is refusing this server’s lookups',
                summary=(
                    f'{zone} answered {count} lookups with "blocked (high volume or public '
                    'resolver)", so its checks are off and spam it would catch gets through. '
                    'The spam filter should be resolving through the stack’s own resolver.'
                ),
                count=int(count),
                first_seen=now - timedelta(hours=1),
                last_seen=now,
                tighten=[health],
            )
        )
    return found
