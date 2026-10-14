"""What the spam filter did with the mail it scanned, from the hourly digest rows.

Rspamd logs one line per scanned message with the action it chose; ``rollup`` keeps a counter per
action per hour. Nothing here knows an address or a subject. Two things are *not* available and
are not guessed: how many of the messages sent to Junk were wanted (a false positive is only known
to the person who found it there) and how many spam messages were let through (they look like
"no action").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# Rspamd's action names as the rollup normalises them (spaces become underscores).
DELIVERED = ('no_action',)
JUNKED = ('add_header', 'rewrite_subject')
DELAYED = ('greylist', 'soft_reject')
REFUSED = ('reject',)
KNOWN = DELIVERED + JUNKED + DELAYED + REFUSED


def _actions(row: dict[str, Any]) -> dict[str, int]:
    found = ((row.get('sources') or {}).get('rspamd') or {}).get('actions') or {}
    return {str(k): int(v or 0) for k, v in found.items()}


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Counts by what happened: scanned, delivered, junked, delayed, refused, other."""
    summed: dict[str, int] = {}
    for row in rows:
        for action, count in _actions(row).items():
            summed[action] = summed.get(action, 0) + count
    scanned = sum(summed.values())
    delivered = sum(summed.get(a, 0) for a in DELIVERED)
    junked = sum(summed.get(a, 0) for a in JUNKED)
    delayed = sum(summed.get(a, 0) for a in DELAYED)
    refused = sum(summed.get(a, 0) for a in REFUSED)
    return {
        'scanned': scanned,
        'delivered': delivered,
        'junked': junked,
        'delayed': delayed,
        'refused': refused,
        'other': scanned - delivered - junked - delayed - refused,
    }


def hourly(
    digests: list[tuple[datetime, dict[str, Any]]], now: datetime, hours: int = 24
) -> list[dict[str, Any]]:
    """One bucket per hour, oldest first, ending with the hour that contains ``now``; hours with
    no digest are zeros, so the chart's width is always the same period."""
    end = now.replace(minute=0, second=0, microsecond=0)
    by_hour = {hour.replace(minute=0, second=0, microsecond=0): row for hour, row in digests}
    out: list[dict[str, Any]] = []
    for step in range(hours - 1, -1, -1):
        hour = end - timedelta(hours=step)
        row = by_hour.get(hour)
        counts = totals([row]) if row else totals([])
        out.append({'hour': hour, **counts, 'caught': counts['junked'] + counts['refused']})
    return out


def bars(buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Heights in percent of the busiest hour (a quiet server still shows its shape), with the
    words for a tooltip and for screen readers."""
    peak = max((b['scanned'] for b in buckets), default=0)
    out = []
    for b in buckets:
        height = round(100 * b['scanned'] / peak) if peak else 0
        out.append(
            {
                'height': max(height, 2) if b['scanned'] else 0,
                'caught': b['caught'],
                'share': round(100 * b['caught'] / b['scanned']) if b['scanned'] else 0,
                'label': f'{b["hour"]:%H:00}: {b["scanned"]} scanned, '
                f'{b["junked"]} to Junk, {b["refused"]} refused',
            }
        )
    return out
