"""Assistant tools offered by the accounts app.

* ``system_health``: the server's own diagnosis.
* ``api_overview``: what the integration API offers, read from the live contract (so the
  assistant cannot describe an endpoint that does not exist, or miss one that does).
* ``api_keys``: which keys exist, who owns them, what they may do and what looks wrong.

Nothing here returns a secret: only key identifiers, which are public by design.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# Scopes that change things; a key holding one without a network list deserves a mention.
_WRITE_SCOPES = frozenset({'mail.manage', 'dns.manage', 'system.manage', 'users.manage'})
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
