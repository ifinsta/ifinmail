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

import contextlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .access_log import _tail, network_of
from .classify import clean
from .types import MailEvent

DEFAULT_DIR = '/var/log/ifinmail-mail'
FILES = ('postfix.log', 'dovecot.log', 'rspamd.log')
SERVICE_OF = {'postfix.log': 'postfix', 'dovecot.log': 'dovecot', 'rspamd.log': 'rspamd'}
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


# Mail flow (counted, never read for content): a message queued, delivered locally (LMTP), sent on,
# deferred or bounced. The queue id is kept so one message can be followed across the three logs.
_QUEUED = re.compile(
    r'postfix/(?:\w+/)?qmgr\[\d+\]: (?P<qid>[0-9A-Za-z]+): '
    r'from=<[^>]*>, size=\d+, nrcpt=\d+ \(queue active\)'
)
_STATUS = re.compile(
    r'postfix/(?:\w+/)?(?P<svc>smtp|lmtp|local|virtual)\[\d+\]: (?P<qid>[0-9A-Za-z]+): to=<[^>]*>, '
    r'(?:orig_to=<[^>]*>, )?relay=[^,]*, .*?status=(?P<status>sent|deferred|bounced)'
)
# Rspamd's one line per message: its verdict, and the queue id Postfix gave the message.
_RSPAMD = re.compile(
    r'rspamd_task_write_log: .*?\(default: [TF] \((?P<action>[^)]+)\): '
    r'\[(?P<score>-?[0-9.]+)/[0-9.]+\]'
)
_QID = re.compile(r'qid: <(?P<qid>[0-9A-Za-z]+)>')
_BLOCKED_DNS = re.compile(r'DNS query blocked on (?P<zone>[a-z0-9.-]+)')


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


def _split(raw: str, now: datetime) -> tuple[datetime, str] | None:
    """A log line's time (UTC) and the rest of it, or ``None`` when it has no readable time."""
    if len(raw) > MAX_LINE:
        return None
    iso = _ISO.match(raw)
    if iso:
        try:
            at = datetime.fromisoformat(iso['stamp'].replace(' ', 'T'))
        except ValueError:
            return None
        return (at if at.tzinfo else at.astimezone()).astimezone(UTC), iso['rest']
    found = _STAMP.match(raw)
    if not found:
        return None
    stamped = _when(found, now)
    return (stamped, found['rest']) if stamped is not None else None


def parse_line(raw: str, now: datetime) -> MailEvent | None:
    split = _split(raw, now)
    if split is None:
        return None
    at, rest = split
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
    match = _STATUS.search(rest)
    if match:
        status, service = match['status'], match['svc']
        kind = status if status != 'sent' else ('delivered' if service != 'smtp' else 'sent')
        return MailEvent(at, '', 'postfix', kind, '', 1, match['qid'])
    match = _QUEUED.search(rest)
    if match:
        return MailEvent(at, '', 'postfix', 'received', '', 1, match['qid'])
    match = _RSPAMD.search(rest)
    if match:
        action = re.sub(r'[^a-z]+', '_', match['action'].lower()).strip('_')
        qid = _QID.search(rest)
        return MailEvent(at, '', 'rspamd', f'spam_{action}', '', 1, qid['qid'] if qid else '')
    match = _BLOCKED_DNS.search(rest)
    if match:
        return MailEvent(at, '', 'rspamd', 'dns_blocked', clean(match['zone'], 60), 1)
    return None


@dataclass(frozen=True)
class SourceStats:
    """What one log file looked like in the window: is it alive, and how busy."""

    exists: bool = False
    size: int = 0
    lines: int = 0  # lines with a readable time inside the window
    last_at: datetime | None = None  # the newest line, anywhere in what was read


def read_window_with_stats(
    since: datetime, now: datetime, *, directory: Path | None = None
) -> tuple[list[MailEvent], dict[str, SourceStats]]:
    """Events at or after ``since`` (oldest first), and per-file statistics."""
    base = directory or log_dir()
    events: list[MailEvent] = []
    stats: dict[str, SourceStats] = {}
    for name in FILES:
        main = base / name
        lines, last_at, size = 0, None, 0
        for path in (main.with_name(name + '.1'), main):
            data, _ = _tail(path, MAX_BYTES)
            with contextlib.suppress(OSError):
                size += path.stat().st_size
            for raw in data.decode('utf-8', 'replace').splitlines():
                split = _split(raw, now)
                if split is None:
                    continue
                if last_at is None or split[0] > last_at:
                    last_at = split[0]
                if split[0] >= since:
                    lines += 1
                    event = parse_line(raw, now)
                    if event is not None:
                        events.append(event)
        stats[SERVICE_OF[name]] = SourceStats(main.exists(), size, lines, last_at)
    events.sort(key=lambda e: e.at)
    return events, stats


def read_window(
    since: datetime, now: datetime, *, directory: Path | None = None
) -> list[MailEvent]:
    """Events at or after ``since``, oldest first; empty when the logs are not there yet."""
    return read_window_with_stats(since, now, directory=directory)[0]


def available(directory: Path | None = None) -> bool:
    base = directory or log_dir()
    return any((base / name).exists() for name in FILES)
