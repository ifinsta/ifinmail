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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey
from backend.services.runtime import read_runtime_file, write_runtime_file

logger = logging.getLogger('backend')

RULES_FILE = 'firewall.nft'
STATUS_FILE = 'firewall-status.json'
DEFAULT_RATE_PER_MINUTE = 120
MAX_BLOCKLIST = 500
_MIN_PREFIX = {4: 8, 6: 16}


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
    up: bool | None
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
            f'"{text}" is not an IP address or network (use 203.0.113.0/24).'
        ) from None


class EntryPointService:
    @staticmethod
    def is_enabled(key: str) -> bool:
        entry = BY_KEY[key]
        if entry.locked:
            return True
        stored = SystemSettings.get(SettingKey.ENTRYPOINTS, {})
        if isinstance(stored, dict) and key in stored:
            return bool(stored[key])
        return True

    @staticmethod
    def set_enabled(key: str, enabled: bool) -> None:
        entry = BY_KEY.get(key)
        if entry is None:
            raise NetworkError('Unknown entry point.')
        if entry.locked and not enabled:
            raise NetworkError(f'{entry.label} cannot be switched off: the server depends on it.')
        stored = SystemSettings.get(SettingKey.ENTRYPOINTS, {})
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored[key] = bool(enabled)
        SystemSettings.set(SettingKey.ENTRYPOINTS, stored)
        EntryPointService.apply()

    # -- blocklist ----------------------------------------------------------
    @staticmethod
    def blocklist() -> list[dict[str, str]]:
        raw = SystemSettings.get(SettingKey.NETWORK_BLOCKLIST, [])
        return (
            [r for r in raw if isinstance(r, dict) and 'cidr' in r] if isinstance(raw, list) else []
        )

    @staticmethod
    def block(cidr: str, note: str = '', *, protect: tuple[str, ...] = ()) -> str:
        """Block a source network. ``protect`` lists addresses that must stay reachable."""
        network = parse_network(cidr)
        if network.prefixlen < _MIN_PREFIX[network.version]:
            raise NetworkError('That network is too large to block.')
        for address in protect:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            if ip in network:
                raise NetworkError(f'That would block {address}, which you are using.')
        rows = EntryPointService.blocklist()
        text = str(network)
        if any(r['cidr'] == text for r in rows):
            raise NetworkError(f'{text} is already blocked.')
        if len(rows) >= MAX_BLOCKLIST:
            raise NetworkError(f'The blocklist is full ({MAX_BLOCKLIST} entries).')
        rows.append(
            {'cidr': text, 'note': note.strip()[:120], 'added': datetime.now(UTC).isoformat()}
        )
        SystemSettings.set(SettingKey.NETWORK_BLOCKLIST, rows)
        EntryPointService.apply()
        return text

    @staticmethod
    def unblock(cidr: str) -> bool:
        rows = EntryPointService.blocklist()
        kept = [r for r in rows if r['cidr'] != cidr]
        if len(kept) == len(rows):
            return False
        SystemSettings.set(SettingKey.NETWORK_BLOCKLIST, kept)
        EntryPointService.apply()
        return True

    # -- rate limit ---------------------------------------------------------
    @staticmethod
    def rate_per_minute() -> int:
        return SystemSettings.get_int(SettingKey.NETWORK_RATE_LIMITS, DEFAULT_RATE_PER_MINUTE)

    @staticmethod
    def set_rate_per_minute(value: int) -> int:
        if not 0 <= value <= 100000:
            raise NetworkError('Enter a number between 0 (no limit) and 100000.')
        if value and value < 20:
            raise NetworkError(
                'Below 20 new connections a minute per address would block real mail servers.'
            )
        SystemSettings.set(SettingKey.NETWORK_RATE_LIMITS, value)
        EntryPointService.apply()
        return value

    # -- rules --------------------------------------------------------------
    @staticmethod
    def render(
        disabled: list[tuple[str, int]] | None = None,
        blocked: list[str] | None = None,
        rate: int | None = None,
    ) -> str:
        """nftables rule set (applied atomically, replacing the previous one)."""
        if disabled is None:
            disabled = [
                (proto.value, port)
                for e in CATALOGUE
                if not EntryPointService.is_enabled(e.key)
                for proto, port in e.ports
            ]
        if blocked is None:
            blocked = [r['cidr'] for r in EntryPointService.blocklist()]
        if rate is None:
            rate = EntryPointService.rate_per_minute()
        v4 = sorted(c for c in blocked if ':' not in c)
        v6 = sorted(c for c in blocked if ':' in c)
        limited = sorted(
            {
                port
                for e in CATALOGUE
                if e.rate_limited and EntryPointService.is_enabled(e.key)
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
            lines.append('  }')
        lines.append('}')
        return '\n'.join(lines) + '\n'

    @staticmethod
    def apply() -> str:
        text = EntryPointService.render()
        write_runtime_file(RULES_FILE, text)
        return text

    @staticmethod
    def agent_status() -> AgentStatus:
        try:
            data = json.loads(read_runtime_file(STATUS_FILE) or 'null')
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return AgentStatus(False, None, False, 'The firewall agent has not reported yet.')
        applied = None
        with contextlib.suppress(ValueError):
            applied = datetime.fromisoformat(str(data.get('updated', '')).replace('Z', '+00:00'))
        fresh = bool(applied and (datetime.now(UTC) - applied).total_seconds() < 120)
        wanted = hashlib.sha256((read_runtime_file(RULES_FILE) or '').encode()).hexdigest()
        in_sync = bool(data.get('ok')) and data.get('sha256') == wanted
        message = str(data.get('message', ''))
        if not fresh:
            message = message or 'The firewall agent is not reporting.'
        return AgentStatus(fresh, applied, fresh and in_sync, message)

    # -- probes -------------------------------------------------------------
    @staticmethod
    def probe(entry: EntryPoint, timeout: float = 1.5) -> Probe:
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
    def probe_all() -> dict[str, Probe]:
        return {e.key: EntryPointService.probe(e) for e in CATALOGUE}
