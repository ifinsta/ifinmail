"""Reading the Postfix and Dovecot logs for what the threat digest cares about.

Both containers write their log to a file on a shared volume (the console reads it read-only) and
forward it to the container output, so ``docker logs`` is unchanged. Like the access log reader,
this one is stateless: it parses the newest part of each file and keeps the events of the window.

Only four things are kept, and none of them is message content: a failed mail sign-in (Postfix
SASL or Dovecot IMAP/POP3), a successful sign-in, a refused attempt to relay through the server,
and a refused recipient that does not exist (someone guessing addresses). A line that matches
none of them is dropped on sight.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .access_log import _tail, network_of
from .classify import clean
from .types import MailEvent

DEFAULT_DIR = '/var/log/ifinmail-mail'
FILES = ('postfix.log', 'dovecot.log')
MAX_BYTES = 12 * 1024 * 1024  # per file, across the file and its rotated copy
MAX_LINE = 2048

_STAMP = re.compile(
    r'^(?P<mon>[A-Z][a-z]{2}) +(?P<day>\d{1,2}) (?P<time>\d\d:\d\d:\d\d) (?P<rest>.*)$'
)
_ISO = re.compile(r'^(?P<stamp>\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[+-]\d\d:?\d\d)?) (?P<rest>.*)$')
_MONTHS = {
    m: i
    for i, m in enumerate(
        ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1
    )
}
_ADDR = r'\[(?P<ip>[0-9A-Fa-f:.]{3,45})\]'
_SASL = re.compile(r'warning: [^\[ ]*' + _ADDR + r': SASL [A-Za-z0-9_-]+ authentication failed')
_RELAY = re.compile(
    r'NOQUEUE: reject: RCPT from [^\[ ]*' + _ADDR + r': \d+ [\d.]+ <[^>]*>: Relay access denied'
)
_UNKNOWN = re.compile(
    r'NOQUEUE: reject: RCPT from [^\[ ]*'
    + _ADDR
    + r': 5\d\d [\d.]+ <[^>]*>: Recipient address rejected: User unknown'
)
_DOVECOT_FAIL = re.compile(
    r'(?:imap|pop3)-login: .*?\(auth failed, (?P<n>\d+) attempts? in \d+ secs\): '
    r'user=<(?P<who>[^>]*)>.*?rip=(?P<ip>[0-9A-Fa-f:.]{3,45})'
)
_DOVECOT_OK = re.compile(
    r'(?:imap|pop3)-login: Info: Login: user=<(?P<who>[^>]*)>.*?rip=(?P<ip>[0-9A-Fa-f:.]{3,45})'
)


def log_dir() -> Path:
    return Path(os.environ.get('IFINMAIL_MAIL_LOG_DIR', DEFAULT_DIR))


def _when(match: re.Match[str], now: datetime) -> datetime | None:
    """Syslog-style stamps carry no year or zone: read them in the server's own zone."""
    try:
        hour, minute, second = (int(part) for part in match['time'].split(':'))
        month, day = _MONTHS[match['mon']], int(match['day'])
        stamp = datetime(now.year, month, day, hour, minute, second)
        at = stamp.astimezone().astimezone(UTC)  # naive -> the process's zone (TZ is shared)
        if at > now + timedelta(days=1):  # a log from before New Year
            at = stamp.replace(year=now.year - 1).astimezone().astimezone(UTC)
        return at
    except (KeyError, ValueError):
        return None


def parse_line(raw: str, now: datetime) -> MailEvent | None:
    if len(raw) > MAX_LINE:
        return None
    at: datetime | None
    iso = _ISO.match(raw)
    if iso:
        try:
            at = datetime.fromisoformat(iso['stamp'].replace(' ', 'T'))
        except ValueError:
            return None
        at = (at if at.tzinfo else at.astimezone()).astimezone(UTC)
        rest = iso['rest']
    else:
        found = _STAMP.match(raw)
        if not found:
            return None
        at = _when(found, now)
        rest = found['rest']
    if at is None:
        return None
    for pattern, kind, service in (
        (_SASL, 'auth_failed', 'postfix'),
        (_RELAY, 'relay_denied', 'postfix'),
        (_UNKNOWN, 'unknown_recipient', 'postfix'),
    ):
        match = pattern.search(rest)
        if match:
            net = network_of(match['ip'])
            return MailEvent(at, net, service, kind, '', 1) if net else None
    match = _DOVECOT_FAIL.search(rest)
    if match:
        net = network_of(match['ip'])
        weight = max(1, min(int(match['n']), 50))
        return (
            MailEvent(at, net, 'dovecot', 'auth_failed', clean(match['who'], 120), weight)
            if net
            else None
        )
    match = _DOVECOT_OK.search(rest)
    if match:
        net = network_of(match['ip'])
        return (
            MailEvent(at, net, 'dovecot', 'login_success', clean(match['who'], 120), 1)
            if net
            else None
        )
    return None


def read_window(
    since: datetime, now: datetime, *, directory: Path | None = None
) -> list[MailEvent]:
    """Events at or after ``since``, oldest first; empty when the logs are not there yet."""
    base = directory or log_dir()
    events: list[MailEvent] = []
    for name in FILES:
        main = base / name
        for path in (main.with_name(name + '.1'), main):
            data, _ = _tail(path, MAX_BYTES)
            for raw in data.decode('utf-8', 'replace').splitlines():
                event = parse_line(raw, now)
                if event is not None and event.at >= since:
                    events.append(event)
    events.sort(key=lambda e: e.at)
    return events


def available(directory: Path | None = None) -> bool:
    base = directory or log_dir()
    return any((base / name).exists() for name in FILES)
