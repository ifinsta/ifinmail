"""Reading nginx's JSON access log (see ``log_format ifinmail_json`` in the nginx config).

The reader is stateless: it parses the newest part of the log and keeps the requests of the
window asked for. That keeps it simple and correct across restarts and rotations, and the cost is
bounded because only the last ``MAX_BYTES`` of the log are read, however large a flood has made it.
A line that is too long, not JSON, or not about a request is counted and skipped, never raised.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .classify import clean
from .types import Access

DEFAULT_PATH = '/var/log/ifinmail/access.json'
MAX_BYTES = 24 * 1024 * 1024  # per run, across both files
MAX_LINE = 4096


@dataclass(frozen=True)
class ReadResult:
    requests: list[Access]
    skipped_bytes: int  # older log left unread because the log was larger than MAX_BYTES
    malformed: int
    available: bool  # False when there is no log (not mounted, or nothing logged yet)


def network_of(ip: str) -> str:
    """The /24 (IPv4) or /48 (IPv6) an address belongs to, as text; '' when it is not an address."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ''
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f'{address}/{prefix}', strict=False))


def log_path() -> Path:
    return Path(os.environ.get('IFINMAIL_ACCESS_LOG', DEFAULT_PATH))


def _tail(path: Path, budget: int) -> tuple[bytes, int]:
    """The last ``budget`` bytes of a file, starting on a line boundary, and the bytes skipped."""
    try:
        size = path.stat().st_size
        with path.open('rb') as handle:
            skipped = max(size - budget, 0)
            handle.seek(skipped)
            data = handle.read(budget)
    except OSError:
        return b'', 0
    if skipped:
        newline = data.find(b'\n')
        data = data[newline + 1 :] if newline >= 0 else b''
    return data, skipped


def parse_line(raw: bytes) -> Access | None:
    if len(raw) > MAX_LINE:
        return None
    try:
        row = json.loads(raw)
        if not isinstance(row, dict):
            return None
        at = datetime.fromisoformat(str(row['t']))
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        uri = str(row.get('uri', ''))
        path, _, query = uri.partition('?')
        ip = str(row.get('ip', ''))
        net = network_of(ip)
        if not net:
            return None
        return Access(
            at=at,
            ip=ip,
            net=net,
            method=str(row.get('m', ''))[:16],
            path=path[:300],
            query=query[:300],
            status=int(row.get('st', 0)),
            host=str(row.get('h', ''))[:100],
            ua=str(row.get('ua', ''))[:200],
            cid=clean(str(row.get('cid', '')), 64),
            seconds=float(row.get('rt', 0) or 0),
        )
    except (ValueError, KeyError, TypeError):
        return None


def read_window(
    since: datetime, *, path: Path | None = None, max_bytes: int = MAX_BYTES
) -> ReadResult:
    """Requests logged at or after ``since``, oldest first."""
    main = path or log_path()
    rotated = main.with_name(main.name + '.1')
    newest, skipped = _tail(main, max_bytes)
    chunks = [newest]
    if skipped == 0 and len(newest) < max_bytes and rotated.exists():
        older, older_skipped = _tail(rotated, max_bytes - len(newest))
        chunks.insert(0, older)
        skipped = older_skipped
    if not any(chunks) and not main.exists():
        return ReadResult([], 0, 0, available=False)
    requests: list[Access] = []
    malformed = 0
    for chunk in chunks:
        for raw in chunk.splitlines():
            if not raw.strip():
                continue
            access = parse_line(raw)
            if access is None:
                malformed += 1
            elif access.at >= since:
                requests.append(access)
    requests.sort(key=lambda a: a.at)
    return ReadResult(requests, skipped, malformed, available=True)


def window_start(now: datetime, minutes: int = 60) -> datetime:
    return now - timedelta(minutes=minutes)
