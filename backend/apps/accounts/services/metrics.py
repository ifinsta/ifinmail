"""Prometheus text exposition of what System health already knows.

No client library: the format is a few lines of text. Everything here is derived from the
cached health report, the audit chain and two counts, so a scrape costs one cache read
(the chain verification is cached separately). No message data, addresses or secrets.
"""

from __future__ import annotations

from django.core.cache import cache

from backend.apps.accounts.services import system_health as sh
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.domains.services import DomainService
from backend.apps.mail.services import MailService

_CHAIN_KEY = 'metrics:audit-chain'
_CHAIN_SECONDS = 600

# alert on >= 2: warning (act soon) and error (act now)
_STATE_VALUE = {
    sh.OK: 0,
    sh.INFO: 0,
    sh.WAITING: 1,
    sh.UNKNOWN: 1,
    sh.WARNING: 2,
    sh.ERROR: 3,
}


def _label(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')


def _chain() -> dict[str, object]:
    cached = cache.get(_CHAIN_KEY)
    if cached is None:
        cached = AuditService.verify_chain()
        cache.set(_CHAIN_KEY, cached, _CHAIN_SECONDS)
    return cached


def render() -> str:
    report = sh.SystemHealth.report()
    chain = _chain()
    lines = [
        '# HELP ifinmail_up The console answered this scrape.',
        '# TYPE ifinmail_up gauge',
        'ifinmail_up 1',
        '# HELP ifinmail_health_check_status System health check result: '
        '0 ok or info, 1 waiting or unknown, 2 warning, 3 error. Alert on 2 or more.',
        '# TYPE ifinmail_health_check_status gauge',
    ]
    for check in sorted(report.checks, key=lambda c: (c.group, c.key)):
        value = _STATE_VALUE.get(check.state, 1)
        lines.append(
            f'ifinmail_health_check_status{{check="{_label(check.key)}",'
            f'group="{_label(check.group)}"}} {value}'
        )
    lines += [
        '# HELP ifinmail_health_checked_timestamp_seconds When the checks last ran.',
        '# TYPE ifinmail_health_checked_timestamp_seconds gauge',
        f'ifinmail_health_checked_timestamp_seconds {int(report.checked_at.timestamp())}',
        '# HELP ifinmail_audit_chain_ok 1 when the audit trail hash chain verifies.',
        '# TYPE ifinmail_audit_chain_ok gauge',
        f'ifinmail_audit_chain_ok {1 if chain["ok"] else 0}',
        '# HELP ifinmail_audit_events Events held in the audit trail.',
        '# TYPE ifinmail_audit_events gauge',
        f'ifinmail_audit_events {chain["checked"]}',
        '# HELP ifinmail_domains Domains served.',
        '# TYPE ifinmail_domains gauge',
        f'ifinmail_domains {DomainService.get_domain_count()}',
        '# HELP ifinmail_mailboxes Mailboxes hosted.',
        '# TYPE ifinmail_mailboxes gauge',
        f'ifinmail_mailboxes {MailService.get_mailbox_count()}',
    ]
    return '\n'.join(lines) + '\n'
