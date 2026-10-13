"""Where an address is: country and network operator, from a file on this server.

The data is the free DB-IP "IP to Country Lite" and "IP to ASN Lite" databases (CC BY 4.0,
https://db-ip.com), downloaded about once a month and turned into one small SQLite file under the
runtime directory. Looking an address up reads that file: no visitor address is ever sent anywhere,
and no extra Python package is needed. Without the file every lookup answers "unknown" and the rest
of the threat digest works as before.

Location is a clue, not evidence: VPNs, proxies and cloud-hosted botnets put an attacker in the
"wrong" country. It is used to group and to notice what is new, never to block by country.
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import io
import ipaddress
import json
import logging
import os
import sqlite3
import tempfile
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.apps.core.platform.services.runtime import runtime_dir

logger = logging.getLogger('backend.telemetry')

ATTRIBUTION = 'IP location data by DB-IP.com (CC BY 4.0)'
BASE_URL = 'https://download.db-ip.com/free'
MAX_DOWNLOAD = 64 * 1024 * 1024
REFRESH_AFTER = timedelta(days=32)
RETRY_AFTER = timedelta(hours=6)
_BATCH = 20000
_FAMILIES = (4, 6)


@dataclass(frozen=True)
class Place:
    country: str = ''  # ISO 3166 two letters; '' when unknown ("ZZ" in the data)
    asn: int = 0
    org: str = ''

    @property
    def known(self) -> bool:
        return bool(self.country or self.asn)

    @property
    def key(self) -> str:
        """A stable name for "somewhere like this": the country and the operator."""
        return f'{self.country or "??"}/AS{self.asn}' if self.asn else (self.country or '')

    def text(self) -> str:
        parts = [self.country] if self.country else []
        if self.asn:
            parts.append(f'AS{self.asn}' + (f' {self.org}' if self.org else ''))
        return ' · '.join(parts)


UNKNOWN = Place()


def db_path() -> Path:
    override = os.environ.get('IFINMAIL_GEO_DB')
    return Path(override) if override else runtime_dir() / 'geo' / 'geo.sqlite'


def _meta_path() -> Path:
    return db_path().with_suffix('.json')


def info() -> dict[str, object] | None:
    """What is installed (``version``, ``built``, ``rows``), or ``None`` when nothing is."""
    try:
        data = json.loads(_meta_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and db_path().exists() else None


def _packed(ip: str) -> tuple[int, bytes] | None:
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.version, address.packed


class Reader:
    """A read-only handle on the file; cheap enough to open once per digest pass or page."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        self._orgs: dict[int, str] = {}

    def close(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self._db.close()

    def __enter__(self) -> Reader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _range(self, table: str, packed: bytes) -> tuple[object, ...] | None:
        row = self._db.execute(
            f'SELECT "end", value FROM {table} WHERE start <= ? ORDER BY start DESC LIMIT 1',  # noqa: S608
            (packed,),
        ).fetchone()
        if row is None or packed > bytes(row[0]):
            return None
        return tuple(row)

    def lookup(self, ip: str) -> Place:
        parsed = _packed(ip)
        if parsed is None:
            return UNKNOWN
        family, packed = parsed
        try:
            country_row = self._range(f'country{family}', packed)
            asn_row = self._range(f'asn{family}', packed)
        except sqlite3.Error:
            return UNKNOWN
        country = str(country_row[1]) if country_row else ''
        asn = int(asn_row[1]) if asn_row and asn_row[1] else 0  # type: ignore[call-overload]
        return Place('' if country in ('', 'ZZ') else country, asn, self._org(asn) if asn else '')

    def lookup_net(self, net: str) -> Place:
        """The place of a network named like ``203.0.113.0/24`` (its first address)."""
        try:
            return self.lookup(str(ipaddress.ip_network(net, strict=False).network_address))
        except ValueError:
            return UNKNOWN

    def _org(self, asn: int) -> str:
        if asn not in self._orgs:
            row = self._db.execute('SELECT name FROM orgs WHERE asn = ?', (asn,)).fetchone()
            self._orgs[asn] = str(row[0]) if row else ''
        return self._orgs[asn]


def reader() -> Reader | None:
    """A reader on the installed data, or ``None`` when there is none (or it is unreadable)."""
    path = db_path()
    if not path.exists():
        return None
    try:
        connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=2)
        connection.execute('SELECT 1 FROM orgs LIMIT 1')
    except sqlite3.Error:
        return None
    return Reader(connection)


# -- building the file -------------------------------------------------------------------------


def _rows(stream: Iterable[str]) -> Iterator[list[str]]:
    for row in csv.reader(stream):
        if len(row) >= 3:
            yield row


def _insert(
    db: sqlite3.Connection, table_prefix: str, rows: Iterable[tuple[bytes, bytes, object, int]]
) -> int:
    batches: dict[int, list[tuple[bytes, bytes, object]]] = {4: [], 6: []}
    total = 0
    for family, start, end, value in ((r[3], r[0], r[1], r[2]) for r in rows):
        batches[family].append((start, end, value))
        if len(batches[family]) >= _BATCH:
            db.executemany(
                f'INSERT OR REPLACE INTO {table_prefix}{family} VALUES (?,?,?)',  # noqa: S608
                batches[family],
            )
            total += len(batches[family])
            batches[family] = []
    for family, batch in batches.items():
        if batch:
            db.executemany(
                f'INSERT OR REPLACE INTO {table_prefix}{family} VALUES (?,?,?)',  # noqa: S608
                batch,
            )
            total += len(batch)
    return total


def _range_rows(
    parsed: Iterable[list[str]], value: object
) -> Iterator[tuple[bytes, bytes, object, int]]:
    for row in parsed:
        a, b = _packed(row[0]), _packed(row[1])
        if a is None or b is None or a[0] != b[0]:
            continue
        yield a[1], b[1], value(row) if callable(value) else value, a[0]


def build(country_csv: Iterable[str], asn_csv: Iterable[str], target: Path, version: str) -> int:
    """Write the SQLite file for ``target`` from the two CSV streams. Returns the row count."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix='geo-', suffix='.sqlite', dir=target.parent)
    os.close(handle)
    temp = Path(temp_name)
    try:
        db = sqlite3.connect(temp)
        db.execute('PRAGMA journal_mode = OFF')
        db.execute('PRAGMA synchronous = OFF')
        for family in _FAMILIES:
            db.execute(
                f'CREATE TABLE country{family} (start BLOB PRIMARY KEY, "end" BLOB, value TEXT)'
            )
            db.execute(
                f'CREATE TABLE asn{family} (start BLOB PRIMARY KEY, "end" BLOB, value INTEGER)'
            )
        db.execute('CREATE TABLE orgs (asn INTEGER PRIMARY KEY, name TEXT)')
        orgs: dict[int, str] = {}
        rows = _insert(
            db, 'country', _range_rows(_rows(country_csv), lambda r: r[2].strip().upper()[:2])
        )

        def asn_value(row: list[str]) -> int:
            try:
                number = int(row[2])
            except ValueError:
                return 0
            if len(row) > 3 and number:
                orgs.setdefault(number, row[3].strip()[:120])
            return number

        rows += _insert(db, 'asn', _range_rows(_rows(asn_csv), asn_value))
        db.executemany('INSERT OR REPLACE INTO orgs VALUES (?,?)', orgs.items())
        db.commit()
        db.close()
        if rows < 100:
            raise ValueError('the location data looks empty')
        os.chmod(temp, 0o644)  # mkstemp makes it private; the console and the worker both read it
        os.replace(temp, target)
        target.with_suffix('.json').write_text(
            json.dumps(
                {
                    'version': version,
                    'built': datetime.now(UTC).isoformat(timespec='seconds'),
                    'rows': rows,
                }
            ),
            encoding='utf-8',
        )
        return rows
    finally:
        with contextlib.suppress(OSError):
            temp.unlink()


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': 'ifinmail-geo-refresh'})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data: bytes = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('the location data is larger than expected')
    return data


def _lines(compressed: bytes) -> io.TextIOWrapper:
    """The text lines of a gzip file, decompressed as they are read (no full copy in memory)."""
    return io.TextIOWrapper(
        gzip.GzipFile(fileobj=io.BytesIO(compressed)), encoding='utf-8', errors='replace'
    )


def _months(now: datetime) -> list[str]:
    previous = (now.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    return [now.strftime('%Y-%m'), previous]


def refresh(now: datetime | None = None) -> dict[str, object]:
    """Download this month's files (or last month's) and rebuild the lookup file."""
    now = now or datetime.now(UTC)
    last_error: Exception | None = None
    for month in _months(now):
        country_url = os.environ.get(
            'GEO_COUNTRY_URL', f'{BASE_URL}/dbip-country-lite-{month}.csv.gz'
        )
        asn_url = os.environ.get('GEO_ASN_URL', f'{BASE_URL}/dbip-asn-lite-{month}.csv.gz')
        try:
            rows = build(
                _lines(_download(country_url)), _lines(_download(asn_url)), db_path(), month
            )
            return {'ok': True, 'version': month, 'rows': rows}
        except Exception as exc:  # network, format or disk problems all mean "keep the old file"
            last_error = exc
            logger.warning('Location data for %s could not be installed: %s', month, exc)
    _note_attempt(now, str(last_error))
    return {'ok': False, 'error': str(last_error)}


def _note_attempt(now: datetime, error: str) -> None:
    path = db_path().with_name('attempt.json')
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'at': now.isoformat(), 'error': error[:200]}), encoding='utf-8')


def due(now: datetime | None = None) -> bool:
    """Whether the data is missing or old, and a retry is not too soon after a failure."""
    now = now or datetime.now(UTC)
    if os.environ.get('GEO_DISABLED', '').lower() in ('1', 'true', 'yes'):
        return False
    attempt = db_path().with_name('attempt.json')
    with contextlib.suppress(OSError, ValueError, KeyError):
        at = datetime.fromisoformat(json.loads(attempt.read_text(encoding='utf-8'))['at'])
        if now - at < RETRY_AFTER:
            return False
    current = info()
    if current is None:
        return True
    try:
        built = datetime.fromisoformat(str(current.get('built', '')))
    except ValueError:
        return True
    return now - built > REFRESH_AFTER


def refresh_if_due(now: datetime | None = None) -> dict[str, object]:
    if not due(now):
        return {'ok': True, 'skipped': True}
    return refresh(now)
