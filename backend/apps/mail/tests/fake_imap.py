"""A small in-memory IMAP server for tests: just what ``imap_reader`` uses, with Dovecot's rules
for the master login (``<mailbox>*ifinmail-console`` and the master password)."""

from __future__ import annotations

import imaplib
import re
from dataclasses import dataclass, field

PASSWORD = 'test-master-secret'


@dataclass
class Stored:
    uid: int
    raw: bytes
    flags: set[str] = field(default_factory=set)


class FakeStore:
    def __init__(self) -> None:
        self.boxes: dict[str, list[Stored]] = {}
        self.next_uid: dict[str, int] = {}
        self.logins: list[str] = []
        self.on_noop = None  # callable run on NOOP (mail "arriving" while waiting)

    def deliver(self, address: str, raw: bytes) -> int:
        uid = self.next_uid.get(address, 1)
        self.next_uid[address] = uid + 1
        self.boxes.setdefault(address, []).append(Stored(uid, raw))
        return uid

    def client(self, *args, **kwargs) -> FakeIMAP:  # noqa: ANN002, ANN003
        return FakeIMAP(self)


class FakeIMAP:
    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.address = ''

    def login(self, user: str, password: str):  # noqa: ANN201
        address, _, master = user.partition('*')
        self.store.logins.append(user)
        if master != 'ifinmail-console' or password != PASSWORD or address not in self.store.boxes:
            raise imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Authentication failed.')
        self.address = address
        return 'OK', [b'Logged in']

    def select(self, mailbox: str, readonly: bool = False):  # noqa: ANN201
        return 'OK', [str(len(self._box())).encode()]

    def _box(self) -> list[Stored]:
        return self.store.boxes.setdefault(self.address, [])

    def _uids(self, spec: str) -> list[int]:
        uids = [m.uid for m in self._box()]
        if spec in ('ALL', '1:*'):
            return uids
        found = re.fullmatch(r'UID (\d+):\*', spec) or re.fullmatch(r'(\d+):\*', spec)
        if found:
            start = int(found.group(1))
            return [u for u in uids if u >= start]
        return [u for u in uids if str(u) in spec.split(',')]

    def uid(self, command: str, *args):  # noqa: ANN002, ANN201
        command = command.upper()
        if command == 'SEARCH':
            return 'OK', [' '.join(str(u) for u in self._uids(args[1])).encode()]
        wanted = set(self._uids(args[0]))
        if command == 'FETCH':
            parts = []
            for m in self._box():
                if m.uid not in wanted:
                    continue
                flags = ' '.join(sorted(m.flags))
                meta = f'{m.uid} (UID {m.uid} RFC822.SIZE {len(m.raw)} FLAGS ({flags}) BODY[] {{{len(m.raw)}}}'
                body = m.raw.split(b'\r\n\r\n')[0] + b'\r\n\r\n' if 'HEADER.FIELDS' in args[1] else m.raw
                parts.append((meta.encode(), body))
                parts.append(b')')
            return 'OK', parts
        if command == 'STORE':
            for m in self._box():
                if m.uid in wanted:
                    m.flags.add(args[2].strip('()'))
            return 'OK', [b'']
        return 'NO', [b'unknown']

    def expunge(self):  # noqa: ANN201
        self.store.boxes[self.address] = [m for m in self._box() if '\\Deleted' not in m.flags]
        return 'OK', [b'']

    def status(self, mailbox: str, items: str):  # noqa: ANN201
        following = self.store.next_uid.get(self.address, 1)
        return 'OK', [f'"INBOX" (UIDVALIDITY 1700000000 UIDNEXT {following})'.encode()]

    def noop(self):  # noqa: ANN201
        if self.store.on_noop:
            self.store.on_noop()
        return 'OK', [b'']

    def logout(self):  # noqa: ANN201
        return 'BYE', [b'']


def message(
    subject: str = 'Your code',
    body: str = 'Your verification code is 482913.',
    *,
    sender: str = 'no-reply@service.example',
    to: str = 'agent@agents.ifinmail.test',
    html: str = '',
) -> bytes:
    lines = [
        f'From: Service <{sender}>',
        f'To: {to}',
        f'Delivered-To: {to}',
        f'Subject: {subject}',
        'Date: Wed, 15 Oct 2026 09:00:00 +0000',
        f'Message-ID: <{abs(hash((subject, body, to)))}@service.example>',
        'MIME-Version: 1.0',
    ]
    if html:
        boundary = 'BOUNDARY'
        lines += [f'Content-Type: multipart/alternative; boundary="{boundary}"', '',
                  f'--{boundary}', 'Content-Type: text/plain; charset=utf-8', '', body,
                  f'--{boundary}', 'Content-Type: text/html; charset=utf-8', '', html,
                  f'--{boundary}--', '']  # fmt: skip
    else:
        lines += ['Content-Type: text/plain; charset=utf-8', '', body]
    return '\r\n'.join(lines).encode()
