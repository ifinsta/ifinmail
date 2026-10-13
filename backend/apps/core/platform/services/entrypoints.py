"""Every way into the server, and the switches that control them.

The catalogue lists each published port. The console stores which of them are enabled, a blocklist
of source networks and a connection-rate limit; ``render_nft`` turns that into an nftables rule set
that the ``firewall`` container (host network, NET_ADMIN) applies within seconds. Rules match the
*published* port of Docker-forwarded traffic (``ct original proto-dst``) as well as plain host
traffic, so they hold even though Docker publishes ports behind the host firewall.

Ports the console itself or inbound mail depend on are locked: they cannot be switched off here, so
no change made in the console can lock the administrator out or stop mail arriving.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import json
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from django.core.cache import cache
from django.utils.translation import gettext as _

from backend.apps.core.platform.services.runtime import read_runtime_file, write_runtime_file
from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

logger = logging.getLogger('backend')

RULES_FILE = 'firewall.nft'
STATUS_FILE = 'firewall-status.json'
DEFAULT_RATE_PER_MINUTE = 120
MAX_BLOCKLIST = 500
# Flood mode (opt-in, temporary): while a distributed flood lasts, the mail-port cap tightens and
# the web ports get a per-address cap they normally do not have. Established connections are
# never touched, and a person's browser opens a handful of connections a minute, not hundreds.
FLOOD_MAIL_PER_MINUTE = 30
FLOOD_WEB_PER_MINUTE = 240
FLOOD_WEB_KEYS = ('http', 'https')
_MIN_PREFIX = {4: 8, 6: 16}
_PROBE_CACHE_KEY = 'entrypoints:probes'
_PROBE_CACHE_SECONDS = 20
_PROBE_TIMEOUT = 1.0
_PROBE_WORKERS = 10


class Proto(StrEnum):
    TCP = 'tcp'
    UDP = 'udp'


@dataclass(frozen=True)
class EntryPoint:
    key: str
    label: str
    ports: tuple[tuple[Proto, int], ...]
    service: str  # compose service that listens (also the probe host)
    description: str
    locked: bool = False  # cannot be switched off from the console
    rate_limited: bool = False  # counted by the connection-rate limit


CATALOGUE: tuple[EntryPoint, ...] = (
    EntryPoint(
        'smtp',
        'SMTP (inbound mail)',
        ((Proto.TCP, 25),),
        'postfix',
        'Other mail servers deliver mail to you here. Required to receive mail.',
        locked=True,
        rate_limited=True,
    ),
    EntryPoint(
        'submission',
        'Submission',
        ((Proto.TCP, 587),),
        'postfix',
        'Mail clients send mail here after signing in (STARTTLS).',
        rate_limited=True,
    ),
    EntryPoint(
        'smtps',
        'SMTPS',
        ((Proto.TCP, 465),),
        'postfix',
        'Mail clients send mail here after signing in (implicit TLS).',
        rate_limited=True,
    ),
    EntryPoint(
        'imaps',
        'IMAPS',
        ((Proto.TCP, 993),),
        'dovecot',
        'Mail clients read mail here (implicit TLS).',
        rate_limited=True,
    ),
    EntryPoint(
        'pop3s',
        'POP3S',
        ((Proto.TCP, 995),),
        'dovecot',
        'Legacy mail clients download mail here (implicit TLS). Switch off if nobody uses POP3.',
        rate_limited=True,
    ),
    EntryPoint(
        'pop3',
        'POP3 (STARTTLS)',
        ((Proto.TCP, 110),),
        'dovecot',
        'Legacy mail clients download mail here (STARTTLS). Switch off if nobody uses POP3.',
        rate_limited=True,
    ),
    EntryPoint(
        'imap',
        'IMAP (STARTTLS)',
        ((Proto.TCP, 143),),
        'dovecot',
        'Mail clients read mail here (STARTTLS). Switch off if every client uses IMAPS.',
        rate_limited=True,
    ),
    EntryPoint(
        'http',
        'HTTP',
        ((Proto.TCP, 80),),
        'nginx',
        'Certificate validation and the redirect to HTTPS.',
        locked=True,
    ),
    EntryPoint(
        'https',
        'HTTPS (console)',
        ((Proto.TCP, 443),),
        'nginx',
        'This console, MTA-STS and mail client auto-configuration.',
        locked=True,
    ),
    EntryPoint(
        'dns',
        'DNS',
        ((Proto.UDP, 53), (Proto.TCP, 53)),
        'dns',
        'Answers DNS queries for the domains this server is authoritative for.',
    ),
)
BY_KEY = {e.key: e for e in CATALOGUE}


class NetworkError(ValueError):
    """The requested change is not allowed (message is safe to show)."""


@dataclass(frozen=True)
class Probe:
    key: str
    up: bool
    millis: int | None = None


@dataclass(frozen=True)
class AgentStatus:
    reporting: bool
    applied_at: datetime | None
    in_sync: bool
    message: str


def parse_network(text: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        return ipaddress.ip_network(text.strip(), strict=False)
    except ValueError:
        raise NetworkError(
            _('"{text}" is not an IP address or network (use 203.0.113.0/24).').format(text=text)
        ) from None


class EntryPointService:
    @staticmethod
    def enabled_map() -> dict[str, bool]:
        """One DB read for every entry point (avoids N queries on the page)."""
        stored = SystemSettings.get(SettingKey.ENTRYPOINTS, {})
        if not isinstance(stored, dict):
            stored = {}
        return {
            key: True if entry.locked else bool(stored.get(key, True))
            for key, entry in BY_KEY.items()
        }

    @staticmethod
    def is_enabled(key: str, _stored: dict | None = None) -> bool:
        entry = BY_KEY[key]
        if entry.locked:
            return True
        if not isinstance(_stored, dict):
            _stored = SystemSettings.get(SettingKey.ENTRYPOINTS, {})
        if isinstance(_stored, dict) and key in _stored:
            return bool(_stored[key])
        return True

    @staticmethod
    def set_enabled(key: str, enabled: bool) -> None:
        entry = BY_KEY.get(key)
        if entry is None:
            raise NetworkError(_('Unknown entry point.'))
        if entry.locked and not enabled:
            raise NetworkError(
                _('{label} cannot be switched off: the server depends on it.').format(
                    label=entry.label
                )
            )

        def _store(stored: Any) -> dict:
            stored = dict(stored) if isinstance(stored, dict) else {}
            stored[key] = bool(enabled)
            return stored

        SystemSettings.mutate(SettingKey.ENTRYPOINTS, _store, {})
        EntryPointService.apply()

    # -- blocklist ----------------------------------------------------------
    @staticmethod
    def blocklist() -> list[dict[str, str]]:
        raw = SystemSettings.get(SettingKey.NETWORK_BLOCKLIST, [])
        return (
            [r for r in raw if isinstance(r, dict) and 'cidr' in r] if isinstance(raw, list) else []
        )

    @staticmethod
    def block(
        cidr: str,
        note: str = '',
        *,
        protect: tuple[str, ...] = (),
        expires_at: datetime | None = None,
    ) -> str:
        """Block a source network. ``protect`` lists addresses that must stay reachable.

        With ``expires_at`` the block lifts itself (see ``expire``): a mistaken /24 must not linger,
        and most scanners move on within a day.
        """
        network = parse_network(cidr)
        if network.prefixlen < _MIN_PREFIX[network.version]:
            raise NetworkError(_('That network is too large to block.'))
        for address in protect:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            if ip in network:
                raise NetworkError(
                    _('That would block {address}, which you are using.').format(address=address)
                )
        text = str(network)

        def _append(rows: Any) -> list[dict[str, str]]:
            rows = (
                [r for r in rows if isinstance(r, dict) and 'cidr' in r]
                if isinstance(rows, list)
                else []
            )
            if any(r['cidr'] == text for r in rows):
                raise NetworkError(_('{net} is already blocked.').format(net=text))
            if len(rows) >= MAX_BLOCKLIST:
                raise NetworkError(
                    _('The blocklist is full ({limit} entries).').format(limit=MAX_BLOCKLIST)
                )
            row = {'cidr': text, 'note': note.strip()[:120], 'added': datetime.now(UTC).isoformat()}
            if expires_at is not None:
                row['expires'] = expires_at.astimezone(UTC).isoformat()
            rows.append(row)
            return rows

        SystemSettings.mutate(SettingKey.NETWORK_BLOCKLIST, _append, [])
        EntryPointService.apply()
        return text

    @staticmethod
    def _expired(row: dict[str, str], now: datetime) -> bool:
        raw = row.get('expires')
        if not raw:
            return False
        try:
            return datetime.fromisoformat(raw) <= now
        except ValueError:
            return False

    @staticmethod
    def active_blocklist(now: datetime | None = None) -> list[dict[str, str]]:
        """The blocklist without entries whose time is up (the rules never include those)."""
        moment = now or datetime.now(UTC)
        return [
            r for r in EntryPointService.blocklist() if not EntryPointService._expired(r, moment)
        ]

    @staticmethod
    def expire(now: datetime | None = None) -> list[str]:
        """Remove entries whose time is up and republish. Returns the networks removed."""
        moment = now or datetime.now(UTC)
        gone: list[str] = []

        def _keep(rows: Any) -> list[dict[str, str]]:
            rows = rows if isinstance(rows, list) else []
            kept = []
            for row in rows:
                if isinstance(row, dict) and EntryPointService._expired(row, moment):
                    gone.append(str(row.get('cidr', '')))
                else:
                    kept.append(row)
            return kept

        SystemSettings.mutate(SettingKey.NETWORK_BLOCKLIST, _keep, [])
        if gone:
            EntryPointService.apply()
        return gone

    @staticmethod
    def unblock(cidr: str) -> bool:
        removed = False

        def _keep(rows: Any) -> list[dict[str, str]]:
            nonlocal removed
            rows = rows if isinstance(rows, list) else []
            kept = [r for r in rows if r.get('cidr') != cidr]
            removed = len(kept) != len(rows)
            return kept

        SystemSettings.mutate(SettingKey.NETWORK_BLOCKLIST, _keep, [])
        if not removed:
            return False
        EntryPointService.apply()
        return True

    # -- rate limit ---------------------------------------------------------
    @staticmethod
    def rate_per_minute() -> int:
        return SystemSettings.get_int(SettingKey.NETWORK_RATE_LIMITS, DEFAULT_RATE_PER_MINUTE)

    @staticmethod
    def set_rate_per_minute(value: int) -> int:
        if not 0 <= value <= 100000:
            raise NetworkError(_('Enter a number between 0 (no limit) and 100000.'))
        if value and value < 20:
            raise NetworkError(
                _('Below 20 new connections a minute per address would block real mail servers.')
            )
        SystemSettings.set(SettingKey.NETWORK_RATE_LIMITS, value)
        EntryPointService.apply()
        return value

    # -- flood mode ---------------------------------------------------------
    @staticmethod
    def flood_until(now: datetime | None = None) -> datetime | None:
        """When flood mode ends, or ``None`` when it is not in force."""
        state = SystemSettings.get(SettingKey.NETWORK_FLOOD, None)
        if not isinstance(state, dict):
            return None
        try:
            until = datetime.fromisoformat(str(state.get('until', '')))
        except ValueError:
            return None
        return until if until > (now or datetime.now(UTC)) else None

    @staticmethod
    def start_flood(until: datetime, reason: str = '') -> bool:
        """Turn flood mode on (or extend it). Returns whether it was off before."""
        was_off = EntryPointService.flood_until() is None
        SystemSettings.set(
            SettingKey.NETWORK_FLOOD,
            {'until': until.astimezone(UTC).isoformat(), 'reason': reason[:200]},
        )
        if was_off:
            EntryPointService.apply()
        return was_off

    @staticmethod
    def end_flood() -> bool:
        """Clear flood mode if it was set (in force or lapsed). Returns whether anything changed."""
        if SystemSettings.get(SettingKey.NETWORK_FLOOD, None) is None:
            return False
        SystemSettings.delete(SettingKey.NETWORK_FLOOD)
        EntryPointService.apply()
        return True

    @staticmethod
    def expire_flood(now: datetime | None = None) -> bool:
        """Clear flood mode once its time is up (the rules already ignore it before this runs)."""
        if SystemSettings.get(SettingKey.NETWORK_FLOOD, None) is None:
            return False
        if EntryPointService.flood_until(now) is not None:
            return False
        return EntryPointService.end_flood()

    @staticmethod
    def effective_rate(flood: bool | None = None) -> int:
        """The mail-port cap in force: the configured one, tightened while flood mode is on."""
        configured = EntryPointService.rate_per_minute()
        if flood is None:
            flood = EntryPointService.flood_until() is not None
        if not flood:
            return configured
        return min(configured, FLOOD_MAIL_PER_MINUTE) if configured else FLOOD_MAIL_PER_MINUTE

    # -- rules --------------------------------------------------------------
    @staticmethod
    def render(
        disabled: list[tuple[str, int]] | None = None,
        blocked: list[str] | None = None,
        rate: int | None = None,
        flood: bool | None = None,
    ) -> str:
        """nftables rule set (applied atomically, replacing the previous one)."""
        enabled = EntryPointService.enabled_map()
        if disabled is None:
            disabled = [
                (proto.value, port)
                for e in CATALOGUE
                if not enabled.get(e.key, True)
                for proto, port in e.ports
            ]
        if blocked is None:
            blocked = [r['cidr'] for r in EntryPointService.active_blocklist()]
        if flood is None:
            flood = EntryPointService.flood_until() is not None
        if rate is None:
            rate = EntryPointService.effective_rate(flood)
        web = sorted(
            {
                port
                for e in CATALOGUE
                if flood and e.key in FLOOD_WEB_KEYS and enabled.get(e.key, True)
                for proto, port in e.ports
                if proto == Proto.TCP
            }
        )
        v4 = sorted(c for c in blocked if ':' not in c)
        v6 = sorted(c for c in blocked if ':' in c)
        limited = sorted(
            {
                port
                for e in CATALOGUE
                if e.rate_limited and enabled.get(e.key, True)
                for proto, port in e.ports
                if proto == Proto.TCP
            }
        )

        def elements(items: list[str]) -> str:
            return f'elements = {{ {", ".join(items)} }}' if items else ''

        lines = [
            '# Generated by ifinmail. Applied by the firewall container; do not edit.',
            'table inet ifinmail',
            'delete table inet ifinmail',
            'table inet ifinmail {',
            '  set blocked4 {',
            '    type ipv4_addr',
            '    flags interval',
            *(['    ' + elements(v4)] if v4 else []),
            '  }',
            '  set blocked6 {',
            '    type ipv6_addr',
            '    flags interval',
            *(['    ' + elements(v6)] if v6 else []),
            '  }',
            '  set flood4 {',
            '    type ipv4_addr',
            '    flags dynamic,timeout',
            '    timeout 5m',
            '    size 65535',
            '  }',
            '  set flood6 {',
            '    type ipv6_addr',
            '    flags dynamic,timeout',
            '    timeout 5m',
            '    size 65535',
            '  }',
            # The web ports keep their own sets: a set's limiter state is per address, so sharing
            # one with the mail ports would apply whichever rate touched the address first.
            *(
                line
                for name, kind in (('floodweb4', 'ipv4_addr'), ('floodweb6', 'ipv6_addr'))
                for line in (
                    f'  set {name} {{',
                    f'    type {kind}',
                    '    flags dynamic,timeout',
                    '    timeout 5m',
                    '    size 65535',
                    '  }',
                )
                if web
            ),
        ]
        # The same checks run for traffic Docker forwards to a container (ct original proto-dst is
        # the port as published) and for traffic addressed to the host itself (dport).
        for chain, hook, match in (
            ('forward', 'forward', 'ct status dnat ct original proto-dst'),
            ('input', 'input', 'th dport'),
        ):
            lines.append(f'  chain {chain} {{')
            lines.append(f'    type filter hook {hook} priority -10; policy accept;')
            lines.append('    ct state established,related accept')
            if chain == 'input':
                lines.append('    iif "lo" accept')
            guard = 'ct status dnat ' if chain == 'forward' else ''
            lines.append(f'    {guard}ip saddr @blocked4 drop')
            lines.append(f'    {guard}ip6 saddr @blocked6 drop')
            for proto in ('tcp', 'udp'):
                ports = sorted(p for pr, p in disabled if pr == proto)
                if ports:
                    sel = f'{match} {{ {", ".join(map(str, ports))} }}'
                    lines.append(f'    meta l4proto {proto} {sel} drop')
            if rate and limited:
                ports = ', '.join(map(str, limited))
                sel = f'{match} {{ {ports} }}'
                lines.append(
                    f'    meta l4proto tcp {sel} ct state new '
                    f'add @flood4 {{ ip saddr limit rate over {rate}/minute }} drop'
                )
                lines.append(
                    f'    meta l4proto tcp {sel} ct state new '
                    f'add @flood6 {{ ip6 saddr limit rate over {rate}/minute }} drop'
                )
            if web:
                sel = f'{match} {{ {", ".join(map(str, web))} }}'
                for name, saddr in (('floodweb4', 'ip'), ('floodweb6', 'ip6')):
                    lines.append(
                        f'    meta l4proto tcp {sel} ct state new '
                        f'add @{name} {{ {saddr} saddr limit rate over '
                        f'{FLOOD_WEB_PER_MINUTE}/minute }} drop'
                    )
            lines.append('  }')
        lines.append('}')
        return '\n'.join(lines) + '\n'

    @staticmethod
    def apply() -> str:
        text = EntryPointService.render()
        write_runtime_file(RULES_FILE, text)
        return text

    @staticmethod
    def reconcile() -> bool:
        """Publish the rules the console intends when the file is missing or has drifted.

        Rules used to be written only when someone changed a setting, so a server nobody had
        touched ran with none in force while the page showed defaults as if they were. This is
        called on a schedule: it writes only when the content differs, so it is cheap and quiet.
        Returns whether it wrote.
        """
        wanted = EntryPointService.render()
        if read_runtime_file(RULES_FILE) == wanted:
            return False
        write_runtime_file(RULES_FILE, wanted)
        return True

    @staticmethod
    def summary() -> dict[str, int]:
        """What the rule set restricts, in plain counts (for status messages)."""
        enabled = EntryPointService.enabled_map()
        closed = sum(1 for e in CATALOGUE if not enabled.get(e.key, True))
        limited = sum(1 for e in CATALOGUE if e.rate_limited and enabled.get(e.key, True))
        return {
            'closed': closed,
            'blocked': len(EntryPointService.active_blocklist()),
            'rate_per_minute': EntryPointService.effective_rate(),
            'rate_limited_ports': limited,
            'flood_mode': int(EntryPointService.flood_until() is not None),
        }

    @staticmethod
    def agent_status() -> AgentStatus:
        try:
            data = json.loads(read_runtime_file(STATUS_FILE) or 'null')
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return AgentStatus(False, None, False, _('The firewall agent has not reported yet.'))
        applied = None
        with contextlib.suppress(ValueError):
            applied = datetime.fromisoformat(str(data.get('updated', '')).replace('Z', '+00:00'))
        fresh = bool(applied and (datetime.now(UTC) - applied).total_seconds() < 120)
        wanted = hashlib.sha256((read_runtime_file(RULES_FILE) or '').encode()).hexdigest()
        in_sync = bool(data.get('ok')) and data.get('sha256') == wanted
        message = str(data.get('message', ''))
        if not fresh:
            message = message or _('The firewall agent is not reporting.')
        return AgentStatus(fresh, applied, fresh and in_sync, message)

    # -- probes -------------------------------------------------------------
    @staticmethod
    def probe(entry: EntryPoint, timeout: float = _PROBE_TIMEOUT) -> Probe:
        """Does the service accept connections from inside the stack?"""
        proto, port = entry.ports[0]
        started = time.monotonic()
        try:
            if proto == Proto.UDP:
                import dns.message
                import dns.query

                from backend.apps.dns.services.server import DNSServerConfig

                host = socket.gethostbyname(DNSServerConfig.query_host())
                dns.query.udp(dns.message.make_query('.', 'NS'), host, port=port, timeout=timeout)
            else:
                with socket.create_connection((entry.service, port), timeout=timeout):
                    pass
        except OSError:
            return Probe(entry.key, False)
        except Exception:  # dns.exception.* : the server did not answer
            return Probe(entry.key, False)
        return Probe(entry.key, True, int((time.monotonic() - started) * 1000))

    @staticmethod
    def probe_all(
        timeout: float = _PROBE_TIMEOUT,
        *,
        use_cache: bool = True,
        max_workers: int = _PROBE_WORKERS,
    ) -> dict[str, Probe]:
        """Probe every entry point concurrently (was sequential: 10 x timeout).

        Results are cached for ``_PROBE_CACHE_SECONDS`` so repeated page loads
        do not re-probe the stack. ``use_cache=False`` forces a fresh check.
        """
        if use_cache:
            try:
                cached = cache.get(_PROBE_CACHE_KEY)
            except Exception:
                cached = None
            if isinstance(cached, dict) and set(cached) == {e.key for e in CATALOGUE}:
                return cached
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            probes = list(pool.map(lambda e: EntryPointService.probe(e, timeout), CATALOGUE))
        result = {p.key: p for p in probes}
        if use_cache:
            with contextlib.suppress(Exception):
                cache.set(_PROBE_CACHE_KEY, result, _PROBE_CACHE_SECONDS)
        return result
