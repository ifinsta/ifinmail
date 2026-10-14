"""The contact directory: every active mailbox as a vCard, handed to the CardDAV server.

Mail apps show a sender's photo when the sender is in the reader's contacts. This service turns
the mailboxes (name, address, photo) into one vCard each under ``<runtime>/directory/people/`` and
writes a manifest of who is in it. The ``dav`` container mirrors that into a read-only address
book that appears in every mailbox's contacts, so a photo set once shows up in iOS, macOS,
Android (DAVx5) and Thunderbird without anyone importing anything.

Off by default: it lists every mailbox to every mailbox, which is right for one team or family
and wrong for a host with unrelated customers. Each person can also hide themselves.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import transaction

from backend.apps.accounts.models import MailUser, UserProfile
from backend.apps.core.platform.services.runtime import runtime_dir, write_runtime_file
from backend.apps.core.services import SystemSettings
from backend.apps.core.types.settings import SettingKey

logger = logging.getLogger(__name__)

PREFIX = 'directory'
PEOPLE = f'{PREFIX}/people'
MANIFEST = f'{PREFIX}/manifest.json'
MAX_ENTRIES = 2000  # a directory this size is already beyond a CardDAV client's comfort


def enabled() -> bool:
    return SystemSettings.get_bool(SettingKey.DIRECTORY_ENABLED, False)


def set_enabled(value: bool) -> None:
    SystemSettings.set(SettingKey.DIRECTORY_ENABLED, bool(value))


def _escape(value: str) -> str:
    """vCard 3.0 TEXT escaping (RFC 2426 §5)."""
    return (
        value.replace('\\', '\\\\')
        .replace('\n', '\\n')
        .replace('\r', '')
        .replace(';', '\\;')
        .replace(',', '\\,')
    )


def _fold(line: str) -> str:
    """Fold a content line at 75 octets (RFC 2426 §2.6), continuing with a single space."""
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return line
    parts, limit = [], 75
    while raw:
        cut = limit
        while cut < len(raw) and (raw[cut] & 0xC0) == 0x80:  # never split a UTF-8 sequence
            cut -= 1
        parts.append(raw[:cut].decode('utf-8'))
        raw, limit = raw[cut:], 74
    return '\r\n '.join(parts)


@dataclass(frozen=True)
class Entry:
    user_id: str
    address: str
    name: str
    photo: bytes | None
    revision: datetime | None

    @property
    def uid(self) -> str:
        return f'ifinmail-{self.user_id}'

    @property
    def filename(self) -> str:
        return f'{self.user_id}.vcf'

    def vcard(self) -> str:
        display = self.name or self.address.split('@', 1)[0]
        words = display.split()
        family = words[-1] if len(words) > 1 else ''
        given = ' '.join(words[:-1]) if len(words) > 1 else display
        lines = [
            'BEGIN:VCARD',
            'VERSION:3.0',
            f'UID:{self.uid}',
            f'FN:{_escape(display)}',
            f'N:{_escape(family)};{_escape(given)};;;',
            f'EMAIL;TYPE=INTERNET,PREF:{_escape(self.address)}',
            f'ORG:{_escape(self.address.split("@", 1)[-1])}',
        ]
        if self.revision:
            lines.append('REV:' + self.revision.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ'))
        if self.photo:
            lines.append('PHOTO;ENCODING=b;TYPE=JPEG:' + base64.b64encode(self.photo).decode())
        lines.append('END:VCARD')
        return '\r\n'.join(_fold(line) for line in lines) + '\r\n'


def entries() -> list[Entry]:
    """Active, visible mailboxes, name order. Photos are included (large size)."""
    hidden = set(
        UserProfile.objects.filter(directory_hidden=True).values_list('user_id', flat=True)
    )
    profiles = {
        p['user_id']: p
        for p in UserProfile.objects.exclude(photo_sha256='').values(
            'user_id', 'photo_large', 'photo_updated_at'
        )
    }
    out: list[Entry] = []
    for user in MailUser.objects.filter(is_active=True).only('id', 'email', 'full_name'):
        if user.id in hidden or '@' not in user.email:
            continue
        profile = profiles.get(user.id)
        out.append(
            Entry(
                user_id=str(user.id),
                address=user.email.lower(),
                name=(user.full_name or '').strip(),
                photo=bytes(profile['photo_large']) if profile and profile['photo_large'] else None,
                revision=profile['photo_updated_at'] if profile else None,
            )
        )
    out.sort(key=lambda e: ((e.name or e.address).lower(), e.address))
    return out[:MAX_ENTRIES]


def publish() -> dict[str, object]:
    """Write the directory (or its absence) to the runtime volume; idempotent.

    Returns a small summary: ``enabled``, ``count``, ``photos``, ``written``, ``removed``.
    """
    from backend.config.branding import brand_name

    people_dir = runtime_dir() / PEOPLE
    written = removed = 0
    if not enabled():
        wanted: dict[str, str] = {}
        manifest: dict[str, object] = {'enabled': False}
        count = photos = 0
    else:
        found = entries()
        wanted = {e.filename: e.vcard() for e in found}
        count, photos = len(found), sum(1 for e in found if e.photo)
        manifest = {
            'enabled': True,
            'name': f'{brand_name()} directory',
            'users': sorted(e.address for e in found),
            'generated_at': datetime.now(UTC).isoformat(timespec='seconds'),
        }

    people_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in wanted.items():
        path = people_dir / filename
        try:
            if path.read_bytes() == text.encode('utf-8'):
                continue
        except OSError:
            pass
        write_runtime_file(f'{PEOPLE}/{filename}', text)
        written += 1
    for path in people_dir.glob('*.vcf'):
        if path.name not in wanted:
            path.unlink(missing_ok=True)
            removed += 1

    digest = hashlib.sha256(
        json.dumps(
            {k: v for k, v in manifest.items() if k != 'generated_at'}, sort_keys=True
        ).encode()
    ).hexdigest()
    manifest['sha256'] = digest
    body = json.dumps(manifest, sort_keys=True)
    write_runtime_file(MANIFEST, body)
    return {
        'enabled': bool(manifest['enabled']),
        'count': count,
        'photos': photos,
        'written': written,
        'removed': removed,
    }


class DirectoryService:
    @staticmethod
    def set_enabled(value: bool) -> None:
        """Switch the directory on or off and publish (or withdraw) it without waiting."""
        set_enabled(value)
        DirectoryService._queue()

    @staticmethod
    def request_publish() -> None:
        """Republish soon, after the surrounding transaction commits. Never raises: a change to
        a photo must not fail because the directory could not be queued (the periodic task
        catches up)."""
        if enabled():
            DirectoryService._queue()

    @staticmethod
    def _queue() -> None:
        def _go() -> None:
            try:
                from backend.apps.accounts.tasks import publish_directory

                publish_directory.delay()
            except Exception:  # broker down: the five-minute reconcile publishes it
                logger.warning('Could not queue the directory publish', exc_info=True)

        transaction.on_commit(_go)
