"""Containment of a suspected compromised mailbox.

A stolen password is the most damaging thing that can happen to a mail server's reputation, and
rate limits only slow it down. Rspamd counts, per logged-in mailbox, the messages, distinct
recipients and distinct recipient domains of the last hour (``IFINMAIL_OUTBOUND_COUNT`` in
``rspamd.local.lua``, in Redis under ``ifinmail:out:<login>:{m,r,d}``). This module, run every
minute by the worker, compares those counters with the thresholds of the Outbound policy plugin
and, when one is crossed:

* ``notify``  records it, tells the administrators, and shows it in System health;
* ``pause``   additionally adds the login to ``paused`` state, which is published (through the
  plugin layer's dynamic source) to Postfix, so that mailbox's submission is refused until an
  administrator resumes it.

The reaction takes at most about a minute; what a mailbox can send in that minute is bounded by
the per-minute sending limit and the recipients-per-message limit.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.mail import send_mail

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

logger = logging.getLogger('backend')

CAPABILITY = 'sending.containment'
KEY_PREFIX = 'ifinmail:out:'
_KEY_RE = re.compile(r'^' + re.escape(KEY_PREFIX) + r'(?P<login>.+):m$')
ALERT_EVERY = timedelta(hours=1)
SCAN_LIMIT = 5000  # mailboxes looked at per run; a hosted server has far fewer


@dataclass(frozen=True)
class Thresholds:
    action: str
    max_messages: int
    max_recipients: int
    max_domains: int
    notify: tuple[str, ...]


@dataclass(frozen=True)
class Usage:
    login: str
    messages: int
    recipients: int
    domains: int

    def over(self, limits: Thresholds) -> list[str]:
        reasons = []
        if self.messages > limits.max_messages:
            reasons.append(f'{self.messages} messages (limit {limits.max_messages})')
        if self.recipients > limits.max_recipients:
            reasons.append(
                f'{self.recipients} different recipients (limit {limits.max_recipients})'
            )
        if self.domains > limits.max_domains:
            reasons.append(
                f'{self.domains} different recipient domains (limit {limits.max_domains})'
            )
        return reasons


# ------------------------------------------------------------------------------------ state


def paused() -> dict[str, dict]:
    """``{login: {reason, at, usage}}`` of mailboxes whose sending is paused."""
    value = SystemSettings.get(SettingKey.SENDING_PAUSED, {}) or {}
    return value if isinstance(value, dict) else {}


def thresholds() -> Thresholds | None:
    """The plugin's settings, or None when Outbound policy is not installed (nothing to do)."""
    values = InstallationService.capability_values(CAPABILITY)
    action = values.get('action', '')
    if action not in ('notify', 'pause'):
        return None
    try:
        return Thresholds(
            action=action,
            max_messages=int(values.get('max_messages') or 300),
            max_recipients=int(values.get('max_recipients') or 500),
            max_domains=int(values.get('max_domains') or 100),
            notify=tuple(x for x in (values.get('notify') or '').split(',') if x),
        )
    except ValueError:
        logger.warning('Containment thresholds are not numbers; containment skipped')
        return None


def redis_client() -> Any:
    import redis

    return redis.Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))


def read_usage(client: Any) -> list[Usage]:
    out: list[Usage] = []
    for raw in client.scan_iter(match=f'{KEY_PREFIX}*:m', count=500):
        key = raw.decode() if isinstance(raw, bytes) else str(raw)
        match = _KEY_RE.match(key)
        if match is None:
            continue
        login = match.group('login')
        base = f'{KEY_PREFIX}{login}'
        messages = client.get(f'{base}:m')
        out.append(
            Usage(
                login=login,
                messages=int(messages or 0),
                recipients=int(client.scard(f'{base}:r') or 0),
                domains=int(client.scard(f'{base}:d') or 0),
            )
        )
        if len(out) >= SCAN_LIMIT:
            break
    return out


# --------------------------------------------------------------------------------- actions


def _publish() -> None:
    try:
        InstallationService.publish_all()
    except Exception:  # the next reconcile (every 10 minutes) writes it
        logger.exception('Could not publish the paused senders; reconcile will retry')


def _recipients_of_alerts(extra: tuple[str, ...]) -> list[str]:
    from backend.apps.accounts.models import MailUser

    found = {a.lower() for a in extra}
    admin = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    if admin:
        found.add(admin)
    found.update(
        e.lower()
        for e in MailUser.objects.filter(is_superuser=True, is_active=True).values_list(
            'email', flat=True
        )
    )
    return sorted(found)


def _notify(subject: str, body: str, extra: tuple[str, ...]) -> None:
    recipients = _recipients_of_alerts(extra)
    if not recipients:
        return
    try:
        send_mail(subject, body, None, recipients, fail_silently=False)
    except Exception:  # a mail problem must not undo the pause
        logger.exception('Could not email the containment alert')


def _alert_due(login: str, now: datetime) -> bool:
    def mark(current: Any) -> dict:
        alerted = dict(current or {})
        last = alerted.get(login)
        if last:
            try:
                if now - datetime.fromisoformat(last) < ALERT_EVERY:
                    return alerted
            except ValueError:
                pass
        alerted[login] = now.isoformat()
        return alerted

    before = SystemSettings.get(SettingKey.SENDING_ALERTED, {}) or {}
    after = SystemSettings.mutate(SettingKey.SENDING_ALERTED, mark, {})
    return after.get(login) != before.get(login)


def pause(login: str, reason: str, usage: Usage | None, *, actor: str = 'system') -> bool:
    """Record a pause and publish it. Returns False when the login was already paused."""
    login = login.strip().lower()
    entry = {
        'reason': reason,
        'at': datetime.now(UTC).isoformat(),
        'usage': (
            {'messages': usage.messages, 'recipients': usage.recipients, 'domains': usage.domains}
            if usage
            else {}
        ),
        'by': actor,
    }
    created = False

    def add(current: Any) -> dict:
        nonlocal created
        state = dict(current or {})
        if login not in state:
            state[login] = entry
            created = True
        return state

    SystemSettings.mutate(SettingKey.SENDING_PAUSED, add, {})
    if created:
        AuditService.record(
            action='sending_paused', user=actor, detail=f'{login}: {reason}', severity='warning'
        )
        _publish()
    return created


def resume(login: str, actor: str) -> bool:
    """Lift a pause, start counting afresh, and publish. Returns False when not paused."""
    login = login.strip().lower()
    removed = False

    def drop(current: Any) -> dict:
        nonlocal removed
        state = dict(current or {})
        removed = state.pop(login, None) is not None
        return state

    SystemSettings.mutate(SettingKey.SENDING_PAUSED, drop, {})
    if not removed:
        return False
    try:
        client = redis_client()
        client.delete(*(f'{KEY_PREFIX}{login}:{suffix}' for suffix in ('m', 'r', 'd')))
    except Exception:
        logger.warning('Could not clear the counters of %s; they expire within an hour', login)
    AuditService.record(action='sending_resumed', user=actor, detail=login)
    _publish()
    return True


# The same atomic script the Rspamd rule runs (rspamd.local.lua): a counter and two sets that
# expire together an hour after the first message.
_COUNT_SCRIPT = """
local window = tonumber(ARGV[1])
local naddr = tonumber(ARGV[2])
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], window) end
for i = 1, naddr do redis.call('SADD', KEYS[2], ARGV[2 + i]) end
if naddr > 0 and redis.call('TTL', KEYS[2]) < 0 then redis.call('EXPIRE', KEYS[2], window) end
local ndom = #ARGV - 2 - naddr
for i = 1, ndom do redis.call('SADD', KEYS[3], ARGV[2 + naddr + i]) end
if ndom > 0 and redis.call('TTL', KEYS[3]) < 0 then redis.call('EXPIRE', KEYS[3], window) end
return n
"""
_WINDOW_SECONDS = 3600


def _short_hash(value: str) -> str:
    # Rspamd's rspamd_cryptobox_hash.create is BLAKE2b; only the counts matter downstream.
    return hashlib.blake2b(value.lower().encode()).hexdigest()[:16]


def record_send(login: str, recipients: list[str], client: Any | None = None) -> None:
    """Count one message sent as ``login`` outside Postfix authentication (the API).

    Mail submitted with a mailbox password is counted by Rspamd; mail an API key sends is not
    authenticated that way, so it is added to the same counters here and containment sees both.
    A Redis outage costs a counter, never a message.
    """
    base = f'{KEY_PREFIX}{login.strip().lower()}'
    addresses = [_short_hash(r) for r in recipients]
    domains = sorted({_short_hash(r.rpartition('@')[2]) for r in recipients})
    try:
        (client or redis_client()).eval(
            _COUNT_SCRIPT,
            3,
            f'{base}:m',
            f'{base}:r',
            f'{base}:d',
            _WINDOW_SECONDS,
            len(addresses),
            *addresses,
            *domains,
        )
    except Exception:
        logger.warning('Could not count an API send for %s', login)


def evaluate(client: Any | None = None, now: datetime | None = None) -> dict[str, list[str]]:
    """Compare every mailbox's counters with the thresholds. Returns ``{paused, alerted}``."""
    limits = thresholds()
    result: dict[str, list[str]] = {'paused': [], 'alerted': []}
    if limits is None:
        return result
    now = now or datetime.now(UTC)
    usage_list = read_usage(client or redis_client())
    already = paused()
    for usage in usage_list:
        reasons = usage.over(limits)
        if not reasons or usage.login in already:
            continue
        reason = 'sent ' + ' and '.join(reasons) + ' in the last hour'
        if limits.action == 'pause':
            if pause(usage.login, reason, usage):
                result['paused'].append(usage.login)
                _notify(
                    f'Sending paused for {usage.login}',
                    f'{usage.login} {reason}. That looks like a compromised password or a '
                    f'runaway program, so its sending was paused.\n\n'
                    'Check the mailbox, change its password if needed, then resume it under '
                    'System health → Paused senders in the console.',
                    limits.notify,
                )
        elif _alert_due(usage.login, now):
            AuditService.record(
                action='sending_alert',
                user='system',
                detail=f'{usage.login}: {reason}',
                severity='warning',
            )
            result['alerted'].append(usage.login)
            _notify(
                f'Unusual sending from {usage.login}',
                f'{usage.login} {reason}. Sending was not paused (the policy only notifies).',
                limits.notify,
            )
    return result
