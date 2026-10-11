"""Custom DNS records an administrator adds to a zone.

Everything the mail server needs (MX, SPF, DKIM, DMARC, MTA-STS, autoconfig, nameservers) is
generated; these records are the extras (a website, a verification token, a subdomain). The rules
here keep a zone valid, because a zone with a CNAME next to other data or a second SPF record
breaks mail delivery in ways that are hard to see.
"""

from __future__ import annotations

import ipaddress
import re

from ..models import CustomDNSRecord
from ..types.zones import CUSTOM_TYPES, RecordType, ZoneRecord

MIN_TTL, MAX_TTL = 60, 86400
_LABEL = r'(?!-)[a-z0-9_-]{1,63}(?<!-)'
_NAME_RE = re.compile(rf'^(@|(\*\.)?{_LABEL}(\.{_LABEL})*)$')
_HOST_RE = re.compile(rf'^({_LABEL}\.)+[a-z0-9-]{{2,63}}$')
_CAA_RE = re.compile(r'^(\d{1,3}) (issue|issuewild|iodef) (\S.*)$')
_SRV_RE = re.compile(r'^(\d{1,5}) (\d{1,5}) (\S+)$')
_MAX_TXT = 2048


class RecordError(ValueError):
    """The record is not valid (message is safe to show)."""


def normalise_name(name: str, zone: str) -> str:
    """Return the owner name relative to the zone ('@' for the apex)."""
    text = (name or '@').strip().lower().rstrip('.')
    if text in ('', '@', zone):
        return '@'
    if text.endswith(f'.{zone}'):
        text = text[: -len(zone) - 1]
    if not _NAME_RE.match(text):
        raise RecordError(f'"{name}" is not a valid record name.')
    return text


def _host(value: str, label: str) -> str:
    host = value.strip().lower().rstrip('.')
    if not _HOST_RE.match(host):
        raise RecordError(f'{label} must be a full hostname such as mail.example.com.')
    return host


def validate_value(rtype: str, value: str, priority: int | None) -> tuple[str, int | None]:
    """Check one record's data; returns the normalised ``(value, priority)``."""
    text = (value or '').strip()
    if not text:
        raise RecordError('Enter a value.')
    if rtype == RecordType.A:
        try:
            return str(ipaddress.IPv4Address(text)), None
        except ValueError:
            raise RecordError('An A record needs an IPv4 address.') from None
    if rtype == RecordType.AAAA:
        try:
            return str(ipaddress.IPv6Address(text)), None
        except ValueError:
            raise RecordError('An AAAA record needs an IPv6 address.') from None
    if rtype in (RecordType.CNAME, RecordType.NS):
        return _host(text, 'The target'), None
    if rtype == RecordType.MX:
        if priority is None or not 0 <= priority <= 65535:
            raise RecordError('An MX record needs a priority between 0 and 65535.')
        return _host(text, 'The mail server'), priority
    if rtype == RecordType.TXT:
        if len(text) > _MAX_TXT:
            raise RecordError('A TXT record can hold at most 2048 characters.')
        if any(ord(c) < 32 for c in text):
            raise RecordError('A TXT record cannot contain control characters.')
        return text, None
    if rtype == RecordType.SRV:
        found = _SRV_RE.match(text)
        if not found or priority is None or not 0 <= priority <= 65535:
            raise RecordError('An SRV record needs a priority and "weight port target".')
        weight, port, target = int(found[1]), int(found[2]), found[3]
        if weight > 65535 or not 0 < port <= 65535:
            raise RecordError('SRV weight and port must be between 0 and 65535.')
        host = '.' if target == '.' else _host(target, 'The target')
        return f'{weight} {port} {host}', priority
    if rtype == RecordType.CAA:
        found = _CAA_RE.match(text)
        if not found or int(found[1]) > 255:
            raise RecordError('A CAA record looks like: 0 issue "letsencrypt.org".')
        return f'{int(found[1])} {found[2]} {found[3].strip().strip(chr(34))}', None
    raise RecordError('Unsupported record type.')


def _managed_conflict(name: str, rtype: str, value: str, managed: list[ZoneRecord]) -> None:
    for record in managed:
        if record.name != name:
            continue
        if rtype == RecordType.CNAME or record.type == RecordType.CNAME:
            raise RecordError(
                f'{name} already has a managed {record.type} record; a CNAME cannot share a name.'
            )
        if rtype == RecordType.TXT and record.type == RecordType.TXT:
            lowered = value.lower()
            for tag in ('v=spf1', 'v=dmarc1', 'v=dkim1', 'v=stsv1'):
                if lowered.startswith(tag) and record.value.lower().startswith(tag):
                    raise RecordError(
                        'ifinmail already manages that record; a second one would break mail.'
                    )
        if (record.type, record.value) == (rtype, value):
            raise RecordError('That record already exists.')


class CustomRecordService:
    @staticmethod
    def list(zone: str) -> list[CustomDNSRecord]:
        return list(CustomDNSRecord.objects.filter(zone=zone))

    @staticmethod
    def as_zone_records(zone: str) -> list[ZoneRecord]:
        return [
            ZoneRecord(
                name=r.name,
                type=r.rtype,
                value=r.value,
                ttl=r.ttl,
                priority=r.priority,
                managed=False,
                record_id=str(r.id),
            )
            for r in CustomRecordService.list(zone)
        ]

    @staticmethod
    def add(
        zone: str,
        *,
        name: str,
        rtype: str,
        value: str,
        ttl: int = 3600,
        priority: int | None = None,
        managed: list[ZoneRecord] | None = None,
    ) -> CustomDNSRecord:
        rtype = (rtype or '').upper()
        if rtype not in {t.value for t in CUSTOM_TYPES}:
            raise RecordError('Choose a record type.')
        rel = normalise_name(name, zone)
        if not MIN_TTL <= int(ttl) <= MAX_TTL:
            raise RecordError(f'TTL must be between {MIN_TTL} and {MAX_TTL} seconds.')
        value, priority = validate_value(rtype, value, priority)
        if rtype == RecordType.NS and rel == '@':
            raise RecordError(
                'The zone apex nameservers are managed; add NS records only for subdomains.'
            )
        if rtype == RecordType.CNAME and rel == '@':
            raise RecordError('A CNAME cannot be placed at the zone apex.')
        existing = CustomRecordService.as_zone_records(zone)
        for other in existing:
            if other.name != rel:
                continue
            if rtype == RecordType.CNAME or other.type == RecordType.CNAME:
                raise RecordError(f'{rel} already has a record; a CNAME must be alone at its name.')
            if rtype == RecordType.TXT and other.type == RecordType.TXT:
                for tag in ('v=spf1', 'v=dmarc1'):
                    if value.lower().startswith(tag) and other.value.lower().startswith(tag):
                        raise RecordError('There is already a record of that kind at this name.')
        _managed_conflict(rel, rtype, value, managed or [])
        record, created = CustomDNSRecord.objects.get_or_create(
            zone=zone,
            name=rel,
            rtype=rtype,
            value=value,
            defaults={'ttl': int(ttl), 'priority': priority},
        )
        if not created:
            raise RecordError('That record already exists.')
        return record

    @staticmethod
    def delete(zone: str, record_id: str) -> bool:
        deleted, _ = CustomDNSRecord.objects.filter(zone=zone, id=record_id).delete()
        return bool(deleted)

    @staticmethod
    def delete_zone(zone: str) -> None:
        CustomDNSRecord.objects.filter(zone=zone).delete()
