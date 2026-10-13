"""Signals that are not in the access log: sign-in outcomes, and the errors a request caused.

Both come from tables that already exist. An audit record carries the client address in its
detail text ("IP: 203.0.113.9" or "bad_secret from 203.0.113.9"), so it is turned into the same
/24 network the access log uses and the two can be read side by side.
"""

from __future__ import annotations

import re
from datetime import datetime

from backend.apps.core.platform.models import AuditEvent
from backend.apps.core.telemetry.models import ErrorEvent

from .access_log import network_of
from .types import AuthEvent

ACTIONS = ('login_failed', 'login_success', 'api_auth_failed', 'mfa_failed', 'stepup_failed')
MAX_EVENTS = 5000
_ADDRESS = re.compile(r'(?:IP: |from )([0-9A-Fa-f:.]{3,45})')
_REASON = re.compile(r'^([a-z_]+) from ')


def auth_events(since: datetime) -> list[AuthEvent]:
    rows = (
        AuditEvent.objects.filter(time__gte=since, action__in=ACTIONS)
        .order_by('time')
        .values_list('time', 'action', 'user', 'detail')[:MAX_EVENTS]
    )
    events: list[AuthEvent] = []
    for at, action, user, detail in rows:
        match = _ADDRESS.search(detail or '')
        reason = ''
        if action == 'api_auth_failed':
            found = _REASON.match(detail or '')
            reason = found.group(1) if found else ''
        who = (user or '')[:190]
        if action == 'api_auth_failed':
            who = who.removeprefix('api:')
        events.append(
            AuthEvent(
                at=at,
                kind=action,
                who=who,
                net=network_of(match.group(1)) if match else '',
                reason=reason,
            )
        )
    return events


def errors_for(correlation_ids: list[str]) -> list[tuple[str, str, str, int]]:
    """Server errors raised while serving the given requests, as (exc_type, view, id, count).

    This is how a probe is tied to a defect: the request id nginx logged is the id the console
    recorded the exception under. Grouped by exception type and view so one bug is one row.
    """
    if not correlation_ids:
        return []
    rows = ErrorEvent.objects.filter(
        correlation_id__in=correlation_ids[:1000], severity__in=['ERROR', 'CRITICAL']
    ).values_list('exc_type', 'view_name', 'correlation_id')
    grouped: dict[tuple[str, str], list[str]] = {}
    for exc_type, view, cid in rows:
        grouped.setdefault((exc_type or 'error', view or ''), []).append(cid)
    return [(t, v, ids[0], len(ids)) for (t, v), ids in grouped.items()]
