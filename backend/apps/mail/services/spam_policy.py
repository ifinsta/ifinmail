"""Spam filtering settings: how strict the filter is and which extra DNS lists it asks.

The administrator sets one number (1 to 10) and a list of DNS providers. This module is the only
place that turns them into engine values: the four Rspamd action thresholds and the provider
list, handed to the plugin layer as a *dynamic source* (``rspamd.policy`` keys that no plugin can
set), so they reach Rspamd through the same validated, acknowledged runtime file as every other
policy. Nothing here writes a file or talks to Rspamd.

Settings live in ``SystemSettings`` (``spam.sensitivity``, ``spam.providers``). Earlier versions
kept them in the branding overrides file; that value is read once as a fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.conf import settings as django_settings

from backend.apps.core.plugins.services import InstallationService, registry
from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey
from backend.config.branding import branding_overrides_path

logger = logging.getLogger('backend')

DEFAULT_LEVEL = 5
MIN_LEVEL, MAX_LEVEL = 1, 10
MAX_PROVIDERS = 20  # Rspamd asks every list for every message: more is slower, not safer

# What each kind of list is for, and what a hit does to a message's score (fixed, and visible as
# its own symbol in the log).
KINDS: dict[str, tuple[str, str, float]] = {
    'dnsbl': ('Sender blocklist', 'The server that delivered the message is listed.', 3.0),
    'uribl': ('Link blocklist', 'A site linked from the message is listed.', 3.0),
    'dnswl': ('Allow list', 'The server that delivered the message is trusted.', -2.0),
}
# The base thresholds are Rspamd's ifinmail defaults (provisioning/docker/rspamd/local.d/actions.conf)
# and are what sensitivity 5 means. Each step stricter lowers them by a tenth of the base.
BASE = {'greylist': 4.0, 'junk': 6.0, 'rewrite': 8.0, 'reject': 15.0}
STEP = 0.1

_HOST_RE = re.compile(
    r'^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$'
)
_TEST_ADDRESS = '2.0.0.127'  # the address every DNS list publishes as its test entry
_LEGACY_KINDS = {'REPUTATION', 'AGGREGATE', 'PASSIVE', 'CUSTOM'}


class SpamSettingError(ValueError):
    """A value the administrator can correct; the message is shown as is."""


# --------------------------------------------------------------------------------- strictness


def clamp_level(value: Any) -> int:
    try:
        level = round(float(value))
    except (TypeError, ValueError):
        raise SpamSettingError('Sensitivity must be a number from 1 to 10.') from None
    if not MIN_LEVEL <= level <= MAX_LEVEL:
        raise SpamSettingError('Sensitivity must be a number from 1 to 10.')
    return level


def thresholds(level: int) -> dict[str, float]:
    """Score at which each action starts, for a sensitivity: 1 is the most permissive, 10 the
    strictest, 5 the ifinmail default. Steps of 0.5 keep the numbers readable."""
    factor = 1 + (DEFAULT_LEVEL - level) * STEP
    return {name: max(0.5, round(base * factor * 2) / 2) for name, base in BASE.items()}


def level() -> int:
    stored = SystemSettings.get(SettingKey.SPAM_SENSITIVITY)
    if stored is None:
        stored = _legacy().get('sensitivity')
    try:
        return clamp_level(stored) if stored is not None else DEFAULT_LEVEL
    except SpamSettingError:
        return DEFAULT_LEVEL


def set_level(value: Any, actor: str) -> int:
    new = clamp_level(value)
    SystemSettings.set(SettingKey.SPAM_SENSITIVITY, new)
    _audit('spam_sensitivity', actor, f'Spam sensitivity set to {new}')
    _publish()
    return new


# --------------------------------------------------------------------------------- providers


@dataclass(frozen=True)
class Provider:
    host: str
    kind: str
    enabled: bool = True
    tested: dict[str, Any] | None = None

    @property
    def label(self) -> str:
        return KINDS[self.kind][0]


def normalize_host(raw: str) -> str:
    host = (raw or '').strip().lower().rstrip('.')
    if '://' in host or '/' in host or '@' in host or ' ' in host:
        raise SpamSettingError('Enter only the DNS name, such as dnsbl.example.org.')
    if not _HOST_RE.match(host) or host.rsplit('.', 1)[1].isdigit():
        raise SpamSettingError(
            'That is not a DNS name: use letters, digits and hyphens in two or more parts.'
        )
    return host


def providers() -> list[Provider]:
    stored = SystemSettings.get(SettingKey.SPAM_PROVIDERS)
    rows = stored if isinstance(stored, list) else _legacy().get('providers') or []
    out: list[Provider] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get('type') or 'dnsbl').lower()
        if kind not in KINDS:
            kind = 'dnsbl'  # the old free-form labels (CUSTOM, REPUTATION, ...)
        try:
            host = normalize_host(str(row.get('host', '')))
        except SpamSettingError:
            continue
        if (host, kind) in seen:
            continue
        seen.add((host, kind))
        tested = row.get('tested') if isinstance(row.get('tested'), dict) else None
        out.append(Provider(host, kind, row.get('enabled', True) is not False, tested))
    return out[:MAX_PROVIDERS]


def _store(items: list[Provider]) -> None:
    SystemSettings.set(
        SettingKey.SPAM_PROVIDERS,
        [
            {'host': p.host, 'type': p.kind, 'enabled': p.enabled, 'tested': p.tested}
            for p in items
        ],
    )


def add_provider(host: str, kind: str, actor: str) -> Provider:
    kind = (kind or '').strip().lower()
    if kind not in KINDS:
        raise SpamSettingError('Choose what kind of list this is.')
    clean = normalize_host(host)
    current = providers()
    if any(p.host == clean for p in current):
        raise SpamSettingError(f'{clean} is already in the list.')
    if len(current) >= MAX_PROVIDERS:
        raise SpamSettingError(
            f'At most {MAX_PROVIDERS} lists: each is asked about every message. Remove one first.'
        )
    added = Provider(clean, kind)
    _store([*current, added])
    _audit('spam_provider_added', actor, f'Added {kind} list {clean}')
    _publish()
    return added


def remove_provider(host: str, actor: str) -> None:
    current = providers()
    kept = [p for p in current if p.host != host]
    if len(kept) == len(current):
        raise SpamSettingError('That list is not in the list.')
    _store(kept)
    _audit('spam_provider_removed', actor, f'Removed list {host}')
    _publish()


def set_provider_enabled(host: str, enabled: bool, actor: str) -> None:
    current = providers()
    if not any(p.host == host for p in current):
        raise SpamSettingError('That list is not in the list.')
    _store([Provider(p.host, p.kind, enabled, p.tested) if p.host == host else p for p in current])
    _audit(
        'spam_provider_enabled' if enabled else 'spam_provider_disabled',
        actor,
        f'{"Enabled" if enabled else "Disabled"} list {host}',
    )
    _publish()


# ------------------------------------------------------------------------------ checking a list


def probe(host: str, kind: str, resolver: Any = None) -> dict[str, Any]:
    """Ask the list about its own test entry the way Rspamd would, and time it.

    ``works`` the list answers and lists its test entry; ``quiet`` the zone exists but does not
    list the test entry (usual for allow lists and some link lists); ``refused`` it answered with
    a "you may not use this list" code (public resolvers are refused by several lists);
    ``missing`` the name does not exist; ``down`` no answer in time."""
    import dns.exception
    import dns.resolver

    if resolver is None:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 3.0
        resolver.timeout = 3.0
    name = f'{"test" if kind == "uribl" else _TEST_ADDRESS}.{host}'
    started = time.monotonic()
    state, detail = 'down', 'No answer within 3 seconds.'
    try:
        answer = resolver.resolve(name, 'A')
        codes = [r.to_text() for r in answer]
        if any(c.startswith('127.255.255.') or c.startswith('127.0.0.255') for c in codes):
            state, detail = 'refused', 'It answered that this server may not use it.'
        else:
            state, detail = 'works', 'It answered for its test entry.'
    except dns.resolver.NXDOMAIN:
        try:
            resolver.resolve(host, 'SOA')
            state, detail = 'quiet', 'The list exists but does not list its test entry.'
        except dns.resolver.NoAnswer:
            state, detail = 'quiet', 'The list exists but does not list its test entry.'
        except dns.resolver.NXDOMAIN:
            state, detail = 'missing', 'That name does not exist in DNS.'
        except dns.exception.DNSException:
            state, detail = 'down', 'No answer within 3 seconds.'
    except dns.resolver.NoAnswer:
        state, detail = 'quiet', 'The list exists but does not list its test entry.'
    except dns.exception.DNSException:
        state, detail = 'down', 'No answer within 3 seconds.'
    return {
        'state': state,
        'ms': int((time.monotonic() - started) * 1000),
        'detail': detail,
        'at': datetime.now(UTC).isoformat(timespec='seconds'),
    }


def test_provider(host: str) -> dict[str, Any]:
    current = providers()
    target = next((p for p in current if p.host == host), None)
    if target is None:
        raise SpamSettingError('That list is not in the list.')
    result = probe(target.host, target.kind)
    _store([Provider(p.host, p.kind, p.enabled, result) if p is target else p for p in current])
    return result


# ------------------------------------------------------------------------------ engine values


def rspamd_values() -> dict[str, dict[str, str]]:
    """The dynamic source: values for ``rspamd.policy`` that live in the console's own settings."""
    t = thresholds(level())
    values = {
        'spam_greylist_score': f'{t["greylist"]:.1f}',
        'spam_junk_score': f'{t["junk"]:.1f}',
        'spam_rewrite_score': f'{t["rewrite"]:.1f}',
        'spam_reject_score': f'{t["reject"]:.1f}',
        'dnsbl_providers': ','.join(f'{p.host}/{p.kind}' for p in providers() if p.enabled),
    }
    return {'rspamd.policy': values}


def applied() -> str:
    """Has Rspamd taken up the latest values: applied, applying, not_applied or unknown."""
    return str(registry.get_target('rspamd.policy').applied_status())


# --------------------------------------------------------------------------------- internals


def _legacy() -> dict[str, Any]:
    """What older versions stored in the branding overrides file (read-only fallback)."""
    base_dir = getattr(django_settings, 'BASE_DIR', None)
    path = branding_overrides_path(base_dir) or os.path.join(
        os.environ.get('APP_DIR', '.'), 'branding_overrides.json'
    )
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    spam = data.get('spam') if isinstance(data, dict) else None
    return spam if isinstance(spam, dict) else {}


def _audit(action: str, actor: str, detail: str) -> None:
    from backend.apps.core.platform.services.audit import AuditService

    AuditService.record(action=action, user=actor or None, detail=detail)


def _publish() -> None:
    try:
        InstallationService.publish_all()
    except Exception:  # reconcile (every 10 minutes) writes it
        logger.exception('Could not publish the spam filtering settings; reconcile will retry')
