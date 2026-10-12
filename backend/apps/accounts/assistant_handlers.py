"""Assistant tools offered by the accounts app: System health, the server's own diagnosis."""

from __future__ import annotations


def _system_health(arguments: dict, context) -> dict:  # noqa: ANN001
    from backend.apps.accounts.services.system_health import SystemHealth

    report = SystemHealth.report(refresh=bool(arguments.get('refresh', False)))
    domain = str(arguments.get('domain', '')).strip().lower()
    checks = [c for c in report.checks if not domain or c.group.lower() == domain]

    def row(check) -> dict:  # noqa: ANN001
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
