"""Assistant tools offered by the accounts app.

* ``system_health``: the server's own diagnosis.
* ``api_overview``: what the integration API offers, read from the live contract (so the
  assistant cannot describe an endpoint that does not exist, or miss one that does).
* ``api_keys``: which keys exist, who owns them, what they may do and what looks wrong.
* ``threat_digest``: scanners and attacks of the last hours, reduced to findings and where to
  tighten (the same facts the Threats page shows; no raw requests, no addresses of people).

Nothing here returns a secret: only key identifiers, which are public by design.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# Scopes that change things; a key holding one without a network list deserves a mention.
_WRITE_SCOPES = frozenset(
    {'mail.manage', 'mail.send', 'dns.manage', 'system.manage', 'users.manage'}
)
_EXPIRING_DAYS = 7
_IDLE_DAYS = 30


def _system_health(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    from backend.apps.accounts.services.system_health import SystemHealth

    report = SystemHealth.report(refresh=bool(arguments.get('refresh', False)))
    domain = str(arguments.get('domain', '')).strip().lower()
    checks = [c for c in report.checks if not domain or c.group.lower() == domain]

    def row(check: Any) -> dict[str, Any]:
        return {
            'check': check.title,
            'group': check.group,
            'state': check.state,
            'finding': check.summary,
            **({'fix': check.fix} if check.fix else {}),
            **({'details': [list(v) for v in check.values]} if check.values else {}),
            **({'page': check.link_label} if check.link_label else {}),
        }

    problems = [row(c) for c in checks if c.state not in ('ok', 'info')]
    return {
        'checked_at': report.checked_at.isoformat(),
        'problems': problems,
        'fine': [f'{c.group}: {c.title}' for c in checks if c.state in ('ok', 'info')],
        'groups': sorted({c.group for c in report.checks}),
    }


def _api_overview(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    from backend.apps.accounts.viewsets.contract import operations
    from backend.config.api_versions import CURRENT, LEGACY_MACHINE_PATHS, VERSIONS

    wanted = str(arguments.get('area', '')).strip().lower()
    current = next(v for v in VERSIONS if v.version == CURRENT)
    catalogue = operations(current.api)
    listed = [
        {
            'method': o.method,
            'path': f'/api/{CURRENT}{o.path}',
            'needs_scope': o.scope or 'none (anonymous)',
            'summary': o.summary,
            'answers': list(o.statuses),
        }
        for o in catalogue
        if not wanted or wanted in o.path.lower() or wanted in ' '.join(o.tags).lower()
    ]
    return {
        'versions': [{'version': v.version, 'status': v.status} for v in VERSIONS],
        'base_path': f'/api/{CURRENT}/',
        'index': '/api/',
        'contract': f'/api/{CURRENT}/openapi.json',
        'authentication': {
            'http_basic': 'curl -u ifm_<key>:ifs_<value> https://<mail host>/api/v1/status',
            'bearer': 'Authorization: Bearer ifm.<key>.ifs_<value>',
            'create_a_key': 'Settings > API keys in the console (needs users.manage); the '
            'value is shown once, a lost one is replaced by rotating the key',
        },
        'rules': [
            'A key never has more power than the person who created it, and keeps being '
            "narrowed by that person's current permissions.",
            'Within a version only additions are made; a breaking change is a new version '
            'beside it.',
            'Lists are paged with ?limit= (default 50, at most 200) and ?offset=; the reply is '
            '{"items": [...], "count": N}.',
            'Errors are {"detail": "..."} with 401, 403, 404, 409, 422 or 429 (Retry-After).',
            'A key has a calls-per-minute limit (default 120) and an optional list of networks.',
            'Logins with console access cannot be changed or created through the API, and '
            'domains cannot be removed through it.',
            'Sending (POST /messages) needs the mail.send scope and a key that names its '
            'allowed senders; it is signed with DKIM, limited by the Outbound policy plugin '
            "and by the key's own daily recipient cap, and 202 means accepted, not delivered. "
            'An Idempotency-Key header makes a retry safe.',
        ],
        'operations': listed,
        'scopes_in_use': sorted({o.scope for o in catalogue if o.scope}),
        'old_paths_that_redirect': {
            **{f'/{old}': f'/api/{CURRENT}/{new}' for old, new in LEGACY_MACHINE_PATHS.items()},
            '/api/<path>': f'/api/{CURRENT}/<path>',
        },
    }


def _api_keys(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    from backend.apps.accounts.services.roles import RoleService
    from backend.apps.accounts.services.tokens import TokenService, key_id
    from backend.apps.core.platform.services.audit import AuditService

    now = datetime.now(UTC)
    keys: list[dict[str, Any]] = []
    findings: list[str] = []
    for row in TokenService.list_all():
        label = f'{row.name} ({key_id(row.prefix)})'
        held = RoleService.effective_permissions(row.user)
        lost = sorted(set(row.scopes or []) - held)
        notes: list[str] = []
        if row.expires_at and row.expires_at <= now:
            notes.append('expired')
        elif row.expires_at and row.expires_at - now <= timedelta(days=_EXPIRING_DAYS):
            notes.append(f'expires in {max((row.expires_at - now).days, 0)} days')
        if not row.user.is_active:
            notes.append('owner is disabled, so the key does not work')
        if lost:
            notes.append(f'owner no longer holds: {", ".join(lost)}')
        if row.last_used_at is None and now - row.created_at > timedelta(days=_IDLE_DAYS):
            notes.append(f'never used in {_IDLE_DAYS}+ days: revoke it if it is not needed')
        if 'mail.send' in (row.scopes or []):
            wide = [s for s in (row.allowed_senders or []) if s.startswith('*@')]
            if wide:
                notes.append(f'can send as anyone on {", ".join(s[2:] for s in wide)}')
        if set(row.scopes or []) & _WRITE_SCOPES and not row.allowed_networks:
            notes.append('can change things and works from any address: consider a network list')
        if row.previous_expires_at and row.previous_expires_at > now:
            notes.append('an older secret still works until the rotation overlap ends')
        findings.extend(f'{label}: {note}' for note in notes)
        keys.append(
            {
                'name': row.name,
                'key': key_id(row.prefix),
                'owner': row.user.email,
                'scopes': list(row.scopes or []),
                'created': row.created_at.date().isoformat(),
                'expires': row.expires_at.date().isoformat() if row.expires_at else None,
                'last_used': row.last_used_at.isoformat() if row.last_used_at else None,
                'last_used_from': row.last_used_ip,
                'only_from_networks': list(row.allowed_networks or []),
                'may_send_as': list(row.allowed_senders or []),
                'recipients_per_day': row.send_limit_per_day,
                'calls_per_minute': row.rate_limit_per_minute,
                'notes': notes,
            }
        )
    day_ago = now - timedelta(days=1)
    failures = AuditService.search(q='api_auth_failed', since=day_ago, page_size=50)
    changes = [
        r
        for r in AuditService.search(q='api_', since=now - timedelta(days=7), page_size=50)['rows']
        if str(r.get('action', '')).startswith('api_') and r.get('action') != 'api_auth_failed'
    ][:15]
    return {
        'keys': keys,
        'count': len(keys),
        'findings': findings,
        'failed_sign_ins_last_24h': failures['total'],
        'recent_failures': [
            {'when': r.get('time'), 'who': r.get('user'), 'why': r.get('detail')}
            for r in failures['rows'][:10]
        ],
        'recent_changes_made_with_keys': [
            {
                'when': r.get('time'),
                'by': r.get('user'),
                'action': r.get('action'),
                'what': r.get('detail'),
            }
            for r in changes
        ],
        'manage_at': 'Settings > API keys',
    }


_WHERE_NAMES = {
    'network': 'Settings > Network & entry points',
    'security': 'Settings > Security',
    'api_keys': 'Settings > API keys',
    'users': 'Settings > Users',
    'logs': 'Settings > Logs',
    'health': 'System health',
}


def _mask(subject: str) -> str:
    local, at, domain = subject.partition('@')
    return f'{local[:1]}***@{domain}' if at and local else subject


def _threat_digest(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    from backend.apps.core.telemetry.models import ThreatDigest, ThreatFinding
    from backend.apps.core.telemetry.threats.types import Severity

    wanted = str(arguments.get('minimum', 'low')).lower()
    floor = next((s for s in Severity if s.word == wanted), Severity.LOW)
    latest = ThreatDigest.objects.order_by('-hour').first()
    rows = (
        ThreatFinding.objects.exclude(status=ThreatFinding.RESOLVED)
        .filter(severity__gte=int(floor))
        .order_by('-severity', '-last_seen')[:15]
    )
    findings = [
        {
            'severity': Severity(min(r.severity, 4)).word,
            'what': r.title,
            'subject': _mask(r.subject),
            'count': r.count,
            'summary': r.summary,
            'where_to_tighten': [
                f'{a.get("label", "")} ({_WHERE_NAMES.get(a.get("where", ""), "console")})'
                for a in (r.tighten or [])
            ],
            'request_ids': list(r.evidence or [])[:3],
            'status': r.status,
        }
        for r in rows
    ]
    summary = (latest.summary if latest else {}) or {}
    return {
        'hour': latest.hour.isoformat(timespec='minutes') if latest else None,
        'gist': latest.gist if latest else 'No digest has been written yet.',
        'written_by': latest.gist_source if latest else None,
        'traffic': {
            key: summary.get(key)
            for key in (
                'requests',
                'clients',
                'peak_per_minute',
                'auth_failures',
                'mail_failures',
                'server_errors',
            )
        },
        'by_class': summary.get('by_class', {}),
        'where_from': {
            'countries': summary.get('countries', {}),
            'operators': (summary.get('providers') or [])[:5],
        },
        'findings': findings,
        'connections': list(latest.correlations or []) if latest else [],
        'safe_to_ignore': list(latest.ignored or []) if latest else [],
        'page': 'Settings > Threats',
    }


def register() -> None:
    from backend.apps.core.assistant.services import tools
    from backend.apps.core.assistant.services.tools import Tool

    tools.register(
        Tool(
            'system_health',
            "The server's own checks: inbound and outbound SMTP, mail queue, blocklists, PTR, "
            'certificate, each domain (MX, SPF, DKIM, DMARC, MTA-STS, delegation), services, '
            'disk, memory, backups, plugins, background jobs, version and security. Problems '
            'come with the finding, the fix and the console page.',
            _system_health,
            parameters={
                'domain': {
                    'type': 'string',
                    'description': 'only the checks of this domain (a group name)',
                },
                'refresh': {
                    'type': 'boolean',
                    'description': 'run the checks now instead of using the last 5 minutes',
                },
            },
        )
    )

    tools.register(
        Tool(
            'api_overview',
            'What the integration API offers: versions, how to authenticate, every operation '
            'with its method, path, the scope it needs and what it answers, the rules '
            '(paging, errors, limits, protected mailboxes) and which old paths redirect. Read '
            'from the live contract. Use it for any question about the API, integrations, '
            'automation or how a program can manage mailboxes, aliases or domains.',
            _api_overview,
            parameters={
                'area': {
                    'type': 'string',
                    'description': 'only operations whose path or tag contains this word, '
                    'for example mailboxes, aliases, domains, health, telemetry or dns',
                },
            },
        )
    )
    tools.register(
        Tool(
            'api_keys',
            'The API keys on this server: name, key identifier, owner, scopes, expiry, last '
            'use, allowed networks, rate limit and what looks wrong (expired, unused, too '
            'broad, owner no longer holds a scope), plus failed authentications of the last '
            'day and recent changes made with keys. Never contains a secret. Use it for '
            'questions about which integrations exist or whether they are safe.',
            _api_keys,
        )
    )
    tools.register(
        Tool(
            'threat_digest',
            'Scanners, floods and guessing against this server over the last hours, reduced to '
            'findings: what, who (as a /24 or /48 network, account names masked), how much, '
            'which sign-in attempts succeeded after failures, probes that made the server raise '
            'an error, and where in the console to tighten. Use it for questions about attacks, '
            'scans, DoS, brute force or whether something looks like a breach.',
            _threat_digest,
            parameters={
                'minimum': {
                    'type': 'string',
                    'description': 'lowest severity to list',
                    'enum': ['info', 'low', 'medium', 'high', 'critical'],
                },
            },
        )
    )
