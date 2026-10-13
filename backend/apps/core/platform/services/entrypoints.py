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
import os
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
FLOOD_WEB_BURST = 60
# Denial-of-service guard (on whenever the connection cap is on): decided in the kernel, in the
# second a limit is crossed, long before the threat digest's next pass.
PENALTY_MINUTES = 10  # an address far over a rate cap loses every new connection for this long
PENALTY_FACTOR = 4  # "far over": this many times the cap. Just over it only loses the excess.
WEB_GUARD_PER_MINUTE = 600  # new web connections a minute per address (a browser opens a handful)
WEB_BURST = 120
MAIL_BURST_MIN = 20  # mail clients open several connections at once; bursts are not floods
MAIL_CONCURRENT = 50  # open mail connections per address (a phone uses 2-5)
WEB_CONCURRENT = 100  # open web connections per address
SCAN_BAN_THRESHOLD = 30  # refused web requests in ~15 s that put an address in the penalty box
# (enforced by the firewall agent from nginx's access log; SCAN_BAN_THRESHOLD in its environment)
_OWN_SIDE = (
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
    '127.0.0.0/8',
    '169.254.0.0/16',
    '::1/128',
    'fc00::/7',
    'fe80::/10',
)
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
    penalised: int = 0  # addresses in the kernel's penalty box right now (agent-reported)
    scan_bans: int = 0  # addresses the agent banned for a refused burst since it started


def parse_network(text: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        return ipaddress.ip_network(text.strip(), strict=False)
    except ValueError:
        raise NetworkError(
            _('"{text}" is not an IP address or network (use 203.0.113.0/24).').format(text=text)
        ) from None


def _collapse(items: list[str], version: int) -> list[str]:
    """Networks of one family, merged so that an nftables interval set never sees an overlap
    (overlapping elements make nft reject the whole rule set)."""
    networks = []
    for item in items:
        try:
            network = ipaddress.ip_network(item.strip(), strict=False)
        except ValueError:
            continue
        if network.version == version:
            networks.append(network)
    return [str(n) for n in ipaddress.collapse_addresses(networks)]  # type: ignore[arg-type]


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

    @staticmethod
    def exempt() -> tuple[list[str], list[str]]:
        """Networks the per-address limits never apply to: this server, its own side, and the
        allow-list of Automatic protection."""
        raw = SystemSettings.get(SettingKey.NETWORK_AUTOBLOCK, None)
        allow = raw.get('allow', []) if isinstance(raw, dict) else []
        own = [os.environ.get('SERVER_IP', ''), os.environ.get('SERVER_IPV6', '')]
        items = [*_OWN_SIDE, *(str(a) for a in allow if isinstance(a, str)), *own]
        return _collapse(items, 4), _collapse(items, 6)

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
        web = sorted(
            {
                port
                for e in CATALOGUE
                if e.key in FLOOD_WEB_KEYS and enabled.get(e.key, True)
                for proto, port in e.ports
                if proto == Proto.TCP
            }
        )
        exempt4, exempt6 = EntryPointService.exempt()
        web_rate, web_burst = (
            (FLOOD_WEB_PER_MINUTE, FLOOD_WEB_BURST) if flood else (WEB_GUARD_PER_MINUTE, WEB_BURST)
        )
        mail_burst = max(MAIL_BURST_MIN, rate // 4) if rate else 0

        def elements(items: list[str]) -> str:
            return f'elements = {{ {", ".join(items)} }}' if items else ''

        def fixed(name: str, kind: str, items: list[str]) -> list[str]:
            items = _collapse(items, 4 if kind == 'ipv4_addr' else 6)
            body = ['    ' + elements(items)] if items else []
            return [f'  set {name} {{', f'    type {kind}', '    flags interval', *body, '  }']

        def dynamic(name: str, kind: str, timeout: str = '') -> list[str]:
            flags = 'dynamic,timeout' if timeout else 'dynamic'
            extra = [f'    timeout {timeout}'] if timeout else []
            return [
                f'  set {name} {{',
                f'    type {kind}',
                f'    flags {flags}',
                *extra,
                '    size 65535',
                '  }',
            ]

        lines = [
            '# Generated by ifinmail. Applied by the firewall container; do not edit.',
            'table inet ifinmail',
            'delete table inet ifinmail',
            'table inet ifinmail {',
            *fixed('blocked4', 'ipv4_addr', v4),
            *fixed('blocked6', 'ipv6_addr', v6),
        ]
        if rate:
            # Per-address limits, all decided in the kernel within the second they are crossed:
            # an address that keeps opening connections faster than the cap is put in the penalty
            # box (every new connection from it dropped) for PENALTY_MINUTES, instead of merely
            # losing the excess. Concurrent connections per address are capped too, so one address
            # cannot hold every login slot or web worker open (slow-request attacks).
            lines += [
                *fixed('exempt4', 'ipv4_addr', exempt4),
                *fixed('exempt6', 'ipv6_addr', exempt6),
                *dynamic('penalty4', 'ipv4_addr', f'{PENALTY_MINUTES}m'),
                *dynamic('penalty6', 'ipv6_addr', f'{PENALTY_MINUTES}m'),
                *dynamic('pen4', 'ipv4_addr', '5m'),
                *dynamic('pen6', 'ipv6_addr', '5m'),
                *dynamic('penweb4', 'ipv4_addr', '5m'),
                *dynamic('penweb6', 'ipv6_addr', '5m'),
                *dynamic('flood4', 'ipv4_addr', '5m'),
                *dynamic('flood6', 'ipv6_addr', '5m'),
                # The web ports keep their own sets: a set's limiter state is per address, so
                # sharing one with the mail ports would apply whichever rate touched it first.
                *dynamic('floodweb4', 'ipv4_addr', '5m'),
                *dynamic('floodweb6', 'ipv6_addr', '5m'),
                *dynamic('conn4', 'ipv4_addr'),
                *dynamic('conn6', 'ipv6_addr'),
                *dynamic('connweb4', 'ipv4_addr'),
                *dynamic('connweb6', 'ipv6_addr'),
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
            if not rate:
                lines.append('  }')
                continue
            lines.append(f'    {guard}ip saddr @exempt4 accept')
            lines.append(f'    {guard}ip6 saddr @exempt6 accept')
            lines.append(f'    {guard}ip saddr @penalty4 drop')
            lines.append(f'    {guard}ip6 saddr @penalty6 drop')
            groups = [
                (limited, 'conn', MAIL_CONCURRENT, 'flood', 'pen', rate, mail_burst),
                (web, 'connweb', WEB_CONCURRENT, 'floodweb', 'penweb', web_rate, web_burst),
            ]
            for ports_of, conn, most, meter, pen, per_minute, burst in groups:
                if not ports_of:
                    continue
                sel = f'meta l4proto tcp {match} {{ {", ".join(map(str, ports_of))} }} ct state new'
                # Far over the cap: a flood, so the address goes in the penalty box. First, so
                # that every attempt counts, even those the open-connection cap would refuse.
                for family, saddr in (('4', 'ip'), ('6', 'ip6')):
                    lines.append(
                        f'    {sel} add @{pen}{family} {{ {saddr} saddr limit rate over '
                        f'{per_minute * PENALTY_FACTOR}/minute '
                        f'burst {burst * PENALTY_FACTOR} packets }} '
                        f'add @penalty{family} {{ {saddr} saddr }} drop'
                    )
                # Too many open at once (slow-request attacks hold connections to exhaust them).
                for family, saddr in (('4', 'ip'), ('6', 'ip6')):
                    lines.append(
                        f'    {sel} add @{conn}{family} {{ {saddr} saddr ct count over {most} }} '
                        'reject with tcp reset'
                    )
                # Just over it: only the excess is dropped (a busy office behind one address
                # retries a moment later rather than being shut out).
                for family, saddr in (('4', 'ip'), ('6', 'ip6')):
                    lines.append(
                        f'    {sel} add @{meter}{family} {{ {saddr} saddr limit rate over '
                        f'{per_minute}/minute burst {burst} packets }} drop'
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

        def count(key: str) -> int:
            try:
                return max(int(data.get(key, 0) or 0), 0) if fresh else 0
            except (TypeError, ValueError):
                return 0

        return AgentStatus(
            fresh, applied, fresh and in_sync, message, count('penalised'), count('scan_bans')
        )

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
