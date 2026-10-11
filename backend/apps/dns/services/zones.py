"""Authoritative zones: what this server publishes for each domain.

The api renders every zone into the shared runtime volume (``dns/zones/<zone>.zone`` plus a
generated Knot configuration); the ``dns`` container notices the change and reloads Knot, which
answers queries and signs the zones with DNSSEC. Nothing here talks to Knot directly, so a
publish never blocks on the DNS server being up.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

from django.utils import timezone

from backend.services.runtime import read_runtime_file, runtime_dir, write_runtime_file

from ..models import DNSProviderConfig, DNSZone
from ..types.zones import DSRecord, RecordType, ZoneMode, ZoneRecord, ZoneView
from . import DNSService
from .records import CustomRecordService
from .server import DNSServerConfig

logger = logging.getLogger('backend')

ZONES_DIR = 'dns/zones'
GENERATED_CONF = 'dns/knot.generated.conf'
DS_DIR = 'dns/ds'
_DS_RE = re.compile(r'\bDS\s+(\d+)\s+(\d+)\s+(\d+)\s+([0-9A-Fa-f]+)')
_REFRESH, _RETRY, _EXPIRE, _MINIMUM = 7200, 1800, 1209600, 3600


@dataclass
class PublishResult:
    zones: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _in_zone(host: str, zone: str) -> str | None:
    """Owner name of ``host`` relative to ``zone``, or None when it is outside it."""
    if host == zone:
        return '@'
    if host.endswith(f'.{zone}'):
        return host[: -len(zone) - 1]
    return None


def _txt(value: str) -> str:
    raw = value.encode()
    chunks = [raw[i : i + 255] for i in range(0, len(raw), 255)] or [b'']
    out = []
    for chunk in chunks:
        text = chunk.decode('utf-8', errors='replace').replace('\\', '\\\\').replace('"', '\\"')
        out.append(f'"{text}"')
    return ' '.join(out)


def _target(host: str) -> str:
    return host if host.endswith('.') else f'{host}.'


def rdata(record: ZoneRecord) -> str:
    kind = record.type
    if kind in (RecordType.A, RecordType.AAAA):
        return record.value
    if kind in (RecordType.CNAME, RecordType.NS):
        return _target(record.value)
    if kind == RecordType.MX:
        return f'{record.priority or 0} {_target(record.value)}'
    if kind == RecordType.TXT:
        return _txt(record.value)
    if kind == RecordType.SRV:
        weight, port, host = record.value.split(' ', 2)
        return f'{record.priority or 0} {weight} {port} {host if host == "." else _target(host)}'
    if kind == RecordType.CAA:
        flags, tag, value = record.value.split(' ', 2)
        return f'{flags} {tag} "{value}"'
    raise ValueError(f'Unsupported record type {kind}')


def render_zone_file(zone: str, records: list[ZoneRecord], serial: int) -> str:
    ns_hosts = DNSServerConfig.ns_hosts()
    primary = _target(ns_hosts[0]) if ns_hosts else _target(f'ns1.{zone}')
    lines = [
        f'$ORIGIN {zone}.',
        '$TTL 3600',
        f'@ IN SOA {primary} {_target(DNSServerConfig.hostmaster(zone))} '
        f'{serial} {_REFRESH} {_RETRY} {_EXPIRE} {_MINIMUM}',
    ]
    for record in sorted(records, key=lambda r: (r.name != '@', r.name, r.type, r.value)):
        lines.append(f'{record.name} {record.ttl} IN {record.type} {rdata(record)}')
    return '\n'.join(lines) + '\n'


class ZoneService:
    @staticmethod
    def domain_ip(zone: str) -> str | None:
        """Per-domain override stored on ``Domain.ip_address`` (subdomain IP), if any."""
        try:
            from backend.apps.domains.models import Domain as _Domain

            row = _Domain.objects.filter(name=zone).values_list('ip_address', flat=True).first()
            return str(row) if row else None
        except Exception:
            return None

    @staticmethod
    def authoritative_children(zone: str) -> list[str]:
        """Authoritative child zones of ``zone`` (e.g. a sub under its parent)."""
        try:
            names = list(
                DNSZone.objects.filter(mode=ZoneMode.AUTHORITATIVE.value).values_list(
                    'zone', flat=True
                )
            )
        except Exception:
            return []
        suffix = f'.{zone}'
        return sorted(n for n in names if n != zone and n.endswith(suffix))

    @staticmethod
    def managed_records(zone: str, ip_address: str | None = None) -> list[ZoneRecord]:
        """The records ifinmail generates for ``zone``: mail, nameservers, CAA, discovery."""
        ip_address = ip_address or ZoneService.domain_ip(zone)
        ipv4 = ip_address or DNSServerConfig.server_ipv4()
        ipv6 = DNSServerConfig.server_ipv6()
        mail_host = DNSServerConfig.mail_hostname() or f'mail.{zone}'
        records: list[ZoneRecord] = []
        for rec in DNSService.build_records(zone, ipv4, ip_address=ip_address):
            if DNSService.has_placeholder([rec]):
                continue  # the DKIM key is not available yet; publish nothing rather than a dud
            records.append(
                ZoneRecord(
                    name=rec.name,
                    type=rec.type,
                    value=rec.value,
                    ttl=rec.ttl,
                    priority=rec.priority if rec.type == 'MX' else None,
                )
            )
        if ipv6:
            records += [
                ZoneRecord(name=name, type='AAAA', value=ipv6) for name in ('@', 'mail', 'mta-sts')
            ]
        ns_hosts = DNSServerConfig.ns_hosts()
        for host in ns_hosts:
            records.append(ZoneRecord(name='@', type='NS', value=host))
            rel = _in_zone(host, zone)
            if rel and rel != '@':
                records.append(ZoneRecord(name=rel, type='A', value=ipv4))
                if ipv6:
                    records.append(ZoneRecord(name=rel, type='AAAA', value=ipv6))
        if DNSServerConfig.caa_enabled():
            records.append(ZoneRecord(name='@', type='CAA', value='0 issue letsencrypt.org'))
        # Best practice: when a child zone (subdomain) is also authoritative here,
        # the parent carries an NS delegation (RFC 1034 zone cut) so resolvers find it.
        # Glue is added only when the nameserver itself lives inside the child.
        for child in ZoneService.authoritative_children(zone):
            rel = child[: -len(zone) - 1]
            for host in ns_hosts:
                records.append(ZoneRecord(name=rel, type='NS', value=host))
                if host == child or host.endswith(f'.{child}'):
                    glue_name = _in_zone(host, zone)
                    child_ip = ZoneService.domain_ip(child) or ipv4
                    if glue_name and glue_name != '@':
                        records.append(ZoneRecord(name=glue_name, type='A', value=child_ip))
                        if ipv6:
                            records.append(ZoneRecord(name=glue_name, type='AAAA', value=ipv6))
        # RFC 6186: lets mail clients find the right ports from the domain alone.
        for name, port in (
            ('_submission._tcp', 587),
            ('_imaps._tcp', 993),
            ('_imap._tcp', 143),
            ('_pop3s._tcp', 995),
            ('_pop3._tcp', 110),
        ):
            records.append(
                ZoneRecord(name=name, type='SRV', value=f'1 {port} {mail_host}', priority=0)
            )
        # RFC 6764: calendar and contact apps find the DAV server (and its path) from the domain.
        for service in ('_caldavs._tcp', '_carddavs._tcp'):
            records.append(
                ZoneRecord(name=service, type='SRV', value=f'1 443 {mail_host}', priority=0)
            )
            records.append(ZoneRecord(name=service, type='TXT', value='path=/dav/'))
        # Hostnames that carry mail: they must resolve even when they live in another zone.
        return records

    @staticmethod
    def records(zone: str, ip_address: str | None = None) -> list[ZoneRecord]:
        ip_address = ip_address or ZoneService.domain_ip(zone)
        managed = ZoneService.managed_records(zone, ip_address=ip_address)
        return managed + CustomRecordService.as_zone_records(zone)

    @staticmethod
    def get(zone: str) -> DNSZone | None:
        return DNSZone.objects.filter(zone=zone).first()

    @staticmethod
    def _provider_connected() -> bool:
        try:
            return DNSProviderConfig.objects.exists()
        except Exception:  # table missing before migrations: treat as none
            return False

    @staticmethod
    def ensure(zone: str, mode: ZoneMode | None = None) -> DNSZone:
        """The zone row, created as authoritative (when the DNS server is on) if missing."""
        # A connected DNS provider means the administrator already chose where DNS lives.
        use_here = DNSServerConfig.enabled() and not ZoneService._provider_connected()
        default = ZoneMode.AUTHORITATIVE if use_here else ZoneMode.EXTERNAL
        row, _ = DNSZone.objects.get_or_create(
            zone=zone, defaults={'mode': (mode or default).value}
        )
        return row

    @staticmethod
    def set_mode(zone: str, mode: ZoneMode) -> DNSZone:
        if mode == ZoneMode.AUTHORITATIVE and not DNSServerConfig.enabled():
            raise ValueError('The DNS server is turned off (DNS_SERVER_ENABLED=0).')
        row = ZoneService.ensure(zone)
        row.mode = mode.value
        row.save(update_fields=['mode', 'updated_at'])
        ZoneService.publish()
        return row

    @staticmethod
    def remove(zone: str) -> None:
        DNSZone.objects.filter(zone=zone).delete()
        CustomRecordService.delete_zone(zone)
        ZoneService.publish()

    @staticmethod
    def _knot_conf(rows: list[DNSZone]) -> str:
        secondaries = DNSServerConfig.secondaries()
        base = DNSServerConfig.container_runtime()
        lines = ['# Generated by ifinmail. Do not edit: changes are overwritten.']
        if secondaries:
            lines.append('remote:')
            lines += [f'  - id: sec{i}\n    address: {ip}' for i, ip in enumerate(secondaries)]
            lines.append('acl:\n  - id: transfer\n    address: [' + ', '.join(secondaries) + ']')
            lines.append('    action: transfer')
        if rows:
            lines.append('zone:')
        for row in rows:
            lines.append(f'  - domain: {row.zone}')
            lines.append(f'    file: {base}/{ZONES_DIR}/{row.zone}.zone')
            if not row.dnssec:
                lines.append('    dnssec-signing: off')
            if secondaries:
                lines.append('    acl: [transfer]')
                lines.append(
                    '    notify: [' + ', '.join(f'sec{i}' for i in range(len(secondaries))) + ']'
                )
        return '\n'.join(lines) + '\n'

    @staticmethod
    def publish() -> PublishResult:
        """Render every authoritative zone and the Knot configuration into the runtime volume."""
        result = PublishResult()
        rows = list(DNSZone.objects.filter(mode=ZoneMode.AUTHORITATIVE.value))
        for row in rows:
            body = render_zone_file(row.zone, ZoneService.records(row.zone), serial=0)
            digest = hashlib.sha256(body.encode()).hexdigest()
            if digest != row.content_hash or not row.serial:
                row.serial = max(row.serial + 1, int(time.time()))
                row.content_hash = digest
                row.published_at = timezone.now()
                row.save(update_fields=['serial', 'content_hash', 'published_at', 'updated_at'])
                result.changed.append(row.zone)
            text = render_zone_file(row.zone, ZoneService.records(row.zone), row.serial)
            write_runtime_file(f'{ZONES_DIR}/{row.zone}.zone', text)
            result.zones.append(row.zone)
        # Zone files for domains that are no longer ours are removed so Knot stops serving them.
        directory = runtime_dir() / ZONES_DIR
        if directory.is_dir():
            for path in directory.glob('*.zone'):
                if path.stem not in result.zones:
                    path.unlink(missing_ok=True)
                    result.removed.append(path.stem)
        write_runtime_file(GENERATED_CONF, ZoneService._knot_conf(rows))
        return result

    @staticmethod
    def ds_records(zone: str) -> list[DSRecord]:
        """DS records Knot reports for the zone (written by the dns container)."""
        text = read_runtime_file(f'{DS_DIR}/{zone}.ds') or ''
        found = []
        for tag, alg, dtype, digest in _DS_RE.findall(text):
            found.append(DSRecord(int(tag), int(alg), int(dtype), digest.lower()))
        return found

    @staticmethod
    def view(zone: str) -> ZoneView:
        row = ZoneService.ensure(zone)
        mode = ZoneMode(row.mode)
        return ZoneView(
            zone=zone,
            mode=mode,
            records=ZoneService.records(zone) if mode == ZoneMode.AUTHORITATIVE else [],
            ds=ZoneService.ds_records(zone) if mode == ZoneMode.AUTHORITATIVE else [],
            serial=row.serial,
        )
