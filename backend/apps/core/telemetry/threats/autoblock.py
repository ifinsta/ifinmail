"""Automatic protection: block a network that is attacking, and tighten during a flood.

On by default (an administrator can turn either part off on the Network page), and every effect
is temporary and recorded. A person cannot be locked out by it: it never touches the server's own
address, ranges on the server's own side, the allow-list, a network somebody signed in from
recently, or a finding an administrator has already acknowledged. It runs after each digest pass,
so a block follows within minutes of the finding that earns it and lifts itself when the time is
up.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.core.mail import send_mail

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.platform.services.entrypoints import (
    FLOOD_MAIL_PER_MINUTE,
    FLOOD_WEB_PER_MINUTE,
    EntryPointService,
    NetworkError,
    parse_network,
)
from backend.apps.core.services import SystemSettings
from backend.apps.core.telemetry.models import KnownPlace, ThreatFinding
from backend.apps.core.types import SettingKey

from . import collect, mail_log, rules
from .access_log import network_of
from .types import Severity

logger = logging.getLogger('backend.telemetry')

HOURS = (1, 6, 24, 72, 168)
DEFAULT_HOURS = 24
MAX_AUTO = 50  # automatic blocks in force at once
MAX_PER_PASS = 10  # a single pass never blocks more than this
MAX_ALLOW = 50
FRESH = timedelta(minutes=70)  # a finding must have been seen in the last pass or two
LOGIN_MEMORY = timedelta(days=7)  # networks people signed in from are never blocked ...
KEY_MEMORY = timedelta(days=30)  # ... nor networks an API key was used from
PLACE_MEMORY = timedelta(days=14)  # ... nor where an account was last seen signing in
FLOOD_HOLD = timedelta(hours=2)  # flood mode lasts this long after the last flood sighting
NOTE = 'Auto: '
MAX_HOURS = 168  # a repeat offender's block doubles each time, up to a week, and still lifts
OFFENCE_MEMORY = timedelta(days=30)  # earlier automatic blocks counted for the doubling
_FULL_NOTICE = 'autoblock:full'


@dataclass(frozen=True)
class Config:
    block: bool = True  # block networks that are attacking
    flood: bool = True  # tighten connection caps during a distributed flood
    hours: int = DEFAULT_HOURS
    allow: tuple[str, ...] = ()  # networks that are never blocked automatically


@dataclass
class Result:
    blocked: list[str] = field(default_factory=list)
    skipped: int = 0  # candidates left alone for a safety reason
    full: bool = False
    flood_started: bool = False
    hours: dict[str, int] = field(default_factory=dict)  # how long each new block lasts


def config() -> Config:
    raw: Any = SystemSettings.get(SettingKey.NETWORK_AUTOBLOCK, None)
    if not isinstance(raw, dict):
        return Config()
    hours = raw.get('hours')
    allow = raw.get('allow')
    return Config(
        block=bool(raw.get('block', True)),
        flood=bool(raw.get('flood', True)),
        hours=hours if hours in HOURS else DEFAULT_HOURS,
        allow=tuple(str(a) for a in allow) if isinstance(allow, list) else (),
    )


def parse_allow(text: str) -> tuple[str, ...]:
    """Networks from free text (one per line or comma separated), normalised and checked."""
    found: list[str] = []
    for part in text.replace(',', '\n').splitlines():
        part = part.strip()
        if not part or part.startswith('#'):
            continue
        text_net = str(parse_network(part))
        if text_net not in found:
            found.append(text_net)
    if len(found) > MAX_ALLOW:
        raise NetworkError(f'At most {MAX_ALLOW} networks can be on the allow-list.')
    return tuple(found)


def save(*, block: bool, flood: bool, hours: int, allow_text: str) -> Config:
    if hours not in HOURS:
        raise NetworkError('Choose one of the offered durations.')
    allow = parse_allow(allow_text)
    SystemSettings.set(
        SettingKey.NETWORK_AUTOBLOCK,
        {'block': bool(block), 'flood': bool(flood), 'hours': hours, 'allow': list(allow)},
    )
    EntryPointService.apply()  # the allow-list is also exempt from the kernel's per-address limits
    return config()


def offences(net: str, now: datetime) -> int:
    """Automatic blocks of this network in the last month (from the audit trail)."""
    from backend.apps.core.platform.models import AuditEvent

    return int(
        AuditEvent.objects.filter(
            action='network_auto_block',
            detail__startswith=f'{net} ',
            time__gte=now - OFFENCE_MEMORY,
        ).count()
    )


def hours_for(net: str, base: int, now: datetime) -> int:
    """The block length: the chosen time, doubled for each earlier offence, at most a week."""
    hours: int = base * 2 ** min(offences(net, now), 8)
    return min(hours, MAX_HOURS)


def _known_good(now: datetime) -> set[str]:
    """Networks real people used lately: a scanner sharing a /24 with them must not cut them off."""
    nets = {
        e.net
        for e in collect.auth_events(now - LOGIN_MEMORY)
        if e.kind == 'login_success' and e.net
    }
    # Mailbox sign-ins (the console's audit trail has none) and the places accounts are known by.
    nets.update(
        e.net
        for e in mail_log.read_window(now - timedelta(hours=1), now)
        if e.kind == 'login_success' and e.net
    )
    nets.update(
        KnownPlace.objects.filter(last_seen__gte=now - PLACE_MEMORY)
        .exclude(net='')
        .values_list('net', flat=True)
    )
    from backend.apps.accounts.models import APIToken

    for address in APIToken.objects.filter(
        last_used_at__gte=now - KEY_MEMORY, last_used_ip__isnull=False
    ).values_list('last_used_ip', flat=True):
        net = network_of(str(address))
        if net:
            nets.add(net)
    return nets


def _own_addresses() -> tuple[str, ...]:
    from backend.apps.dns.services.server import DNSServerConfig

    return tuple(a for a in (DNSServerConfig.server_ipv4(), DNSServerConfig.server_ipv6()) if a)


def _touches(net: str, others: list[str]) -> bool:
    try:
        subject = ipaddress.ip_network(net, strict=False)
    except ValueError:
        return True  # when in doubt, leave it alone
    for other in others:
        try:
            candidate = ipaddress.ip_network(other, strict=False)
        except ValueError:
            continue
        if subject.version == candidate.version and subject.overlaps(candidate):
            return True
    return False


def _tell(subject: str, body: str) -> None:
    if os.environ.get('THREAT_ALERTS', '1').lower() in ('0', 'false', 'no'):
        return
    from backend.apps.mail.services import containment

    recipients = containment._recipients_of_alerts(())  # noqa: SLF001
    if not recipients:
        return
    try:
        send_mail(subject, body, None, recipients, fail_silently=False)
    except Exception:  # a mail problem must not undo the protection
        logger.exception('Could not email the automatic-protection notice')


def _block(cfg: Config, now: datetime) -> Result:
    result = Result()
    candidates = list(
        ThreatFinding.objects.filter(
            status=ThreatFinding.OPEN,
            kind__in=rules.NETWORK_KINDS,
            severity__gte=int(Severity.HIGH),
            last_seen__gte=now - FRESH,
        ).order_by('-severity', '-count', 'key')
    )
    if not candidates:
        return result
    active = EntryPointService.active_blocklist(now)
    in_force = [r['cidr'] for r in active]
    automatic = sum(1 for r in active if str(r.get('note', '')).startswith(NOTE))
    good = _known_good(now)
    own = _own_addresses()
    for row in candidates:
        net = row.subject
        if len(result.blocked) >= MAX_PER_PASS:
            break
        if _touches(net, in_force):
            continue  # already blocked, or inside something that is
        if (
            rules.is_internal(net)
            or net in good
            or _touches(net, list(cfg.allow))
            or _touches(net, list(own))
        ):
            result.skipped += 1
            continue
        if automatic + len(result.blocked) >= MAX_AUTO:
            result.full = True
            break
        hours = hours_for(net, cfg.hours, now)
        try:
            text = EntryPointService.block(
                net,
                f'{NOTE}{row.title}'[:120],
                protect=own,
                expires_at=now + timedelta(hours=hours),
            )
        except NetworkError:
            result.skipped += 1
            continue
        result.blocked.append(text)
        result.hours[text] = hours
        in_force.append(text)
        AuditService.record(
            action='network_auto_block',
            user='system',
            detail=f'{text} for {hours} h ({row.kind}: {row.title}; finding {row.key})',
            severity='warning',
        )
    return result


def run(now: datetime | None = None) -> Result:
    """One pass of automatic protection; does nothing unless it was turned on."""
    now = now or datetime.now(UTC)
    cfg = config()
    result = Result()
    if cfg.block:
        result = _block(cfg, now)
    if cfg.flood:
        recent = now - FRESH
        flooding = (
            ThreatFinding.objects.filter(
                kind='distributed_flood',
                status__in=[ThreatFinding.OPEN, ThreatFinding.ACKNOWLEDGED],
                last_seen__gte=recent,
            ).exists()
            # The adaptive baseline: web traffic far above normal for this hour is a flood too,
            # even when it is spread thinly enough that no single network stands out.
            or ThreatFinding.objects.filter(
                key='surge:requests',
                severity__gte=int(Severity.HIGH),
                status=ThreatFinding.OPEN,
                last_seen__gte=recent,
            ).exists()
        )
        if flooding:
            result.flood_started = EntryPointService.start_flood(
                now + FLOOD_HOLD, 'distributed flood'
            )
            if result.flood_started:
                AuditService.record(
                    action='flood_mode_on',
                    user='system',
                    detail=(
                        f'mail ports at most {FLOOD_MAIL_PER_MINUTE} and web ports at most '
                        f'{FLOOD_WEB_PER_MINUTE} new connections a minute per address'
                    ),
                    severity='warning',
                )
    if result.full and cache.add(_FULL_NOTICE, 1, 3600):
        AuditService.record(
            action='network_auto_block_full',
            user='system',
            detail=f'{MAX_AUTO} automatic blocks are already in force; more candidates were left',
            severity='warning',
        )
    lines = []
    if result.blocked:
        each = ', '.join(
            f'{net} for {result.hours.get(net, cfg.hours)} hours'
            + (
                ' (back again: blocked longer)'
                if result.hours.get(net, cfg.hours) > cfg.hours
                else ''
            )
            for net in result.blocked
        )
        lines.append(
            f'Blocked: {each}. Each one lifts itself; to lift one sooner, remove it under '
            'Settings, Network.'
        )
    if result.flood_started:
        lines.append(
            f'Flood mode is on for the next {int(FLOOD_HOLD.total_seconds() // 3600)} hours: '
            f'mail ports are held to {FLOOD_MAIL_PER_MINUTE} new connections a minute per '
            f'address, web ports to {FLOOD_WEB_PER_MINUTE}.'
        )
    if lines:
        _tell('Automatic protection acted on this server', '\n\n'.join(lines))
    return result
