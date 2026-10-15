"""Reading a mailbox from inside the server, over IMAP, as Dovecot's master user.

The console never opens Dovecot's files (they belong to Dovecot and are private to it). It logs
in to Dovecot on the Docker network as ``<mailbox>*ifinmail-console`` with
``DOVECOT_MASTER_PASSWORD``; Dovecot accepts that login only from private networks and only for
mailboxes that exist. Messages are fetched with ``BODY.PEEK`` so reading never marks them read.

Used by Agent inboxes (an agent reads its own inbox through the API) and Inbox webhooks (new mail
in a watched mailbox becomes an event).
"""

from __future__ import annotations

import email
import html as html_lib
import imaplib
import os
import re
import ssl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime

MASTER_USER = 'ifinmail-console'
DEFAULT_HOST = 'dovecot'
PORT = 993
TIMEOUT_SECONDS = 15
MAX_MESSAGE_BYTES = 25 * 1024 * 1024
SNIPPET_CHARS = 200
_INVISIBLE = re.compile('[​-‏ -‮⁠-⁤﻿­]')
_TAGS = re.compile(r'<[^>]+>')
_BLOCKS = re.compile(r'(?is)<(script|style|head)[^>]*>.*?</\1>')


class ReaderError(Exception):
    """The mailbox could not be read; the message is safe to show."""


@dataclass(frozen=True)
class Summary:
    uid: int
    message_id: str
    sender: str
    to: tuple[str, ...]
    subject: str
    date: str  # ISO 8601, UTC when the header had a zone
    size: int
    seen: bool

    def as_dict(self) -> dict:
        return {
            'uid': self.uid,
            'message_id': self.message_id,
            'from': self.sender,
            'to': list(self.to),
            'subject': self.subject,
            'date': self.date,
            'size': self.size,
            'seen': self.seen,
        }


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    size: int


@dataclass
class Message:
    summary: Summary
    text: str
    html: str
    reply_to: str
    cc: tuple[str, ...]
    delivered_to: tuple[str, ...]
    headers: dict[str, str]
    attachments: list[Attachment] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            **self.summary.as_dict(),
            'cc': list(self.cc),
            'reply_to': self.reply_to,
            'delivered_to': list(self.delivered_to),
            'text': self.text,
            'html': self.html,
            'headers': self.headers,
            'attachments': [
                {'filename': a.filename, 'content_type': a.content_type, 'size': a.size}
                for a in self.attachments
            ],
        }


def configured() -> bool:
    return bool(os.environ.get('DOVECOT_MASTER_PASSWORD'))


def _context() -> ssl.SSLContext:
    # The link is the server's own Docker network; Dovecot's certificate names the public host,
    # not "dovecot", so the name is not checked. Encryption still applies.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


@contextmanager
def session(address: str, *, writable: bool = False) -> Iterator[imaplib.IMAP4]:
    """An IMAP session on one mailbox's INBOX."""
    password = os.environ.get('DOVECOT_MASTER_PASSWORD', '')
    if not password:
        raise ReaderError(
            'Mail cannot be read: DOVECOT_MASTER_PASSWORD is not set (run make update to add it).'
        )
    host = os.environ.get('IFINMAIL_IMAP_HOST', DEFAULT_HOST)
    try:
        imap = imaplib.IMAP4_SSL(host, PORT, ssl_context=_context(), timeout=TIMEOUT_SECONDS)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ReaderError('The mail store is not answering. Try again shortly.') from exc
    try:
        try:
            imap.login(f'{address}*{MASTER_USER}', password)
        except imaplib.IMAP4.error as exc:
            raise ReaderError(f'{address} cannot be opened.') from exc
        status, _ = imap.select('INBOX', readonly=not writable)
        if status != 'OK':
            raise ReaderError(f'The inbox of {address} cannot be opened.')
        yield imap
    finally:
        try:
            imap.logout()
        except Exception:  # the connection may already be gone
            pass


# ------------------------------------------------------------------------------ reading


def _decode(value: str | None) -> str:
    if not value:
        return ''
    try:
        return str(email.header.make_header(email.header.decode_header(value)))
    except Exception:
        return value


def _addresses(values: list[str]) -> tuple[str, ...]:
    return tuple(addr.lower() for _, addr in getaddresses([v for v in values if v]) if addr)


def _iso(date_header: str) -> str:
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError):
        return ''
    return parsed.isoformat(timespec='seconds') if parsed else ''


def summary_of(uid: int, raw_headers: bytes, size: int, flags: str) -> Summary:
    msg = email.message_from_bytes(raw_headers, policy=default_policy)
    senders = _addresses([str(msg.get('From', ''))])
    return Summary(
        uid=uid,
        message_id=str(msg.get('Message-ID', '')).strip().strip('<>'),
        sender=senders[0] if senders else '',
        to=_addresses([str(msg.get('To', ''))]),
        subject=_decode(str(msg.get('Subject', '')))[:998],
        date=_iso(str(msg.get('Date', ''))),
        size=size,
        seen='\\Seen' in flags,
    )


_FETCH = re.compile(rb'UID (\d+)')
_SIZE = re.compile(rb'RFC822\.SIZE (\d+)')
_FLAGS = re.compile(rb'FLAGS \(([^)]*)\)')


def _parse_fetch(data: list) -> list[tuple[int, int, str, bytes]]:
    """``(uid, size, flags, payload)`` from imaplib's FETCH answer."""
    out = []
    for item in data:
        if not isinstance(item, tuple):
            continue
        meta, payload = item[0], item[1]
        uid = _FETCH.search(meta)
        if not uid:
            continue
        size = _SIZE.search(meta)
        flags = _FLAGS.search(meta)
        out.append(
            (
                int(uid.group(1)),
                int(size.group(1)) if size else len(payload or b''),
                (flags.group(1) if flags else b'').decode(),
                payload or b'',
            )
        )
    return out


def list_messages(address: str, *, since_uid: int = 0, limit: int = 50) -> list[Summary]:
    """Newest first. ``since_uid``: only messages that arrived after that uid."""
    with session(address) as imap:
        return _list(imap, since_uid=since_uid, limit=limit)


def _list(imap: imaplib.IMAP4, *, since_uid: int, limit: int) -> list[Summary]:
    query = f'UID {since_uid + 1}:*' if since_uid else 'ALL'
    status, found = imap.uid('SEARCH', None, query)
    if status != 'OK':
        return []
    uids = [int(u) for u in (found[0] or b'').split() if int(u) > since_uid]
    uids = sorted(uids, reverse=True)[: max(1, min(limit, 200))]
    if not uids:
        return []
    status, data = imap.uid(
        'FETCH',
        ','.join(str(u) for u in uids),
        '(UID RFC822.SIZE FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])',
    )
    if status != 'OK':
        return []
    rows = [summary_of(uid, payload, size, flags) for uid, size, flags, payload in _parse_fetch(data)]
    return sorted(rows, key=lambda r: r.uid, reverse=True)


def get_message(address: str, uid: int) -> Message | None:
    with session(address) as imap:
        status, data = imap.uid('FETCH', str(uid), '(UID RFC822.SIZE FLAGS BODY.PEEK[])')
        if status != 'OK':
            return None
        found = _parse_fetch(data)
    if not found:
        return None
    uid_, size, flags, raw = found[0]
    return parse(uid_, raw[:MAX_MESSAGE_BYTES], size, flags)


def parse(uid: int, raw: bytes, size: int, flags: str = '') -> Message:
    msg: EmailMessage = email.message_from_bytes(raw, policy=default_policy)  # type: ignore[assignment]
    text_part = msg.get_body(preferencelist=('plain',))
    html_part = msg.get_body(preferencelist=('html',))
    text = _content(text_part)
    html = _content(html_part)
    if not text and html:
        text = html_to_text(html)
    attachments = [
        Attachment(
            filename=_decode(part.get_filename() or '')[:255],
            content_type=part.get_content_type(),
            size=len(part.get_payload(decode=True) or b''),
        )
        for part in msg.iter_attachments()
    ]
    keep = ('From', 'To', 'Cc', 'Reply-To', 'Subject', 'Date', 'Message-ID', 'In-Reply-To',
            'References', 'List-Unsubscribe', 'Authentication-Results', 'X-Spam', 'X-Agent-Risk')  # fmt: skip
    headers = {name: _decode(str(msg.get(name))) for name in keep if msg.get(name) is not None}
    summary = summary_of(uid, raw.split(b'\r\n\r\n', 1)[0].split(b'\n\n', 1)[0], size, flags)
    return Message(
        summary=summary,
        text=text,
        html=html,
        reply_to=(_addresses([str(msg.get('Reply-To', ''))]) or ('',))[0],
        cc=_addresses([str(msg.get('Cc', ''))]),
        delivered_to=_addresses([str(v) for v in msg.get_all('Delivered-To', [])]),
        headers=headers,
        attachments=attachments,
    )


def _content(part) -> str:  # noqa: ANN001
    if part is None:
        return ''
    try:
        return str(part.get_content())
    except (LookupError, ValueError):
        payload = part.get_payload(decode=True) or b''
        return payload.decode('utf-8', 'replace')


def html_to_text(html: str) -> str:
    text = _BLOCKS.sub(' ', html)
    text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</li>', '\n', text)
    text = html_lib.unescape(_TAGS.sub(' ', text))
    lines = [' '.join(line.split()) for line in text.splitlines()]
    return '\n'.join(line for line in lines if line).strip()


def snippet(text: str) -> str:
    flat = ' '.join(_INVISIBLE.sub('', text).split())
    return flat[:SNIPPET_CHARS]


# ------------------------------------------------------------------------------ changing


def delete_message(address: str, uid: int) -> bool:
    with session(address, writable=True) as imap:
        status, _ = imap.uid('STORE', str(uid), '+FLAGS.SILENT', '(\\Deleted)')
        imap.expunge()
        return status == 'OK'


def mark_seen(address: str, uid: int) -> None:
    with session(address, writable=True) as imap:
        imap.uid('STORE', str(uid), '+FLAGS.SILENT', '(\\Seen)')


def empty(address: str) -> None:
    """Remove every message (before an agent inbox is deleted, so no mail stays on disk)."""
    with session(address, writable=True) as imap:
        status, found = imap.uid('SEARCH', None, 'ALL')
        if status == 'OK' and (found[0] or b'').strip():
            imap.uid('STORE', '1:*', '+FLAGS.SILENT', '(\\Deleted)')
            imap.expunge()


def mailbox_state(address: str) -> tuple[int, int]:
    """``(uidvalidity, uidnext)`` of the INBOX: how watchers tell new mail apart."""
    with session(address) as imap:
        status, data = imap.status('INBOX', '(UIDVALIDITY UIDNEXT)')
    if status != 'OK':
        raise ReaderError(f'The inbox of {address} cannot be read.')
    text = (data[0] or b'').decode()
    validity = re.search(r'UIDVALIDITY (\d+)', text)
    following = re.search(r'UIDNEXT (\d+)', text)
    return (int(validity.group(1)) if validity else 0, int(following.group(1)) if following else 1)


def wait_for(address: str, *, since_uid: int, timeout: float, interval: float = 1.0) -> list[Summary]:
    """Messages newer than ``since_uid``, waiting up to ``timeout`` seconds for the first one."""
    deadline = time.monotonic() + max(0.0, timeout)
    with session(address) as imap:
        while True:
            found = _list(imap, since_uid=since_uid, limit=20)
            if found or time.monotonic() >= deadline:
                return found
            time.sleep(interval)
            imap.noop()  # lets Dovecot report mail that arrived meanwhile
