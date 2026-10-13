"""``manage.py storage``: the store from the command line (backups, checks, moving media).

  storage check [--purpose media|backups]     write, read back and remove a test object
  storage status                              where each purpose's files live
  storage upload --purpose backups NAME       stream standard input into backups/NAME
  storage prune --purpose backups --days N    remove backups older than N days
  storage list --purpose backups              list stored backups
  storage sync-media                          copy media on this server's disk to the external store

``make backup`` uses ``upload`` and ``prune``; the archive arrives on standard input already
encrypted (names must end in .gpg: a plaintext backup never leaves the server).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from backend.apps.core.storage import config
from backend.apps.core.storage.contract import StorageError, check_key


class Command(BaseCommand):
    help = 'Work with the configured file store (check, status, upload, prune, list, sync-media).'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            'action', choices=['check', 'status', 'upload', 'prune', 'list', 'sync-media']
        )
        parser.add_argument('name', nargs='?', default='')
        parser.add_argument('--purpose', choices=list(config.PURPOSES), default='media')
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args: Any, **options: Any) -> None:
        action, purpose = options['action'], options['purpose']
        try:
            getattr(self, '_' + action.replace('-', '_'))(purpose, options)
        except StorageError as exc:
            raise CommandError(str(exc)) from exc

    def _status(self, purpose: str, options: dict[str, Any]) -> None:
        for name, where in config.describe()['purposes'].items():
            self.stdout.write(f'{name}: {where["driver"]} — {where["where"]}')

    def _check(self, purpose: str, options: dict[str, Any]) -> None:
        result = config.store_for(purpose).probe()
        self.stdout.write(('OK ' if result.ok else 'FAILED ') + result.detail)
        if not result.ok:
            raise CommandError(result.detail)

    def _upload(self, purpose: str, options: dict[str, Any]) -> None:
        name = options['name']
        if purpose == 'backups' and not name.endswith('.gpg'):
            raise CommandError('Backups leave this server encrypted: the name must end in .gpg.')
        key = check_key(f'{purpose}/{name}' if purpose == 'backups' else name)
        info = config.store_for(purpose).put_stream(
            key, sys.stdin.buffer, content_type='application/octet-stream'
        )
        self.stdout.write(f'Stored {key}: {info.size} bytes, sha256 {info.sha256}')

    def _list(self, purpose: str, options: dict[str, Any]) -> None:
        prefix = 'backups/' if purpose == 'backups' else ''
        for item in config.store_for(purpose).list(prefix, limit=10_000):
            when = item.modified.isoformat(timespec='seconds') if item.modified else '?'
            self.stdout.write(f'{when}  {item.size:>14}  {item.key}')

    def _prune(self, purpose: str, options: dict[str, Any]) -> None:
        if purpose != 'backups':
            raise CommandError('Only backups are pruned by age.')
        days = max(int(options['days']), 1)
        cutoff = datetime.now(UTC) - timedelta(days=days)
        store = config.store_for(purpose)
        removed = 0
        for item in store.list('backups/', limit=10_000):
            if item.modified is not None and item.modified < cutoff:
                store.delete(item.key)
                removed += 1
        self.stdout.write(f'Removed {removed} backup(s) older than {days} days.')

    def _sync_media(self, purpose: str, options: dict[str, Any]) -> None:
        if config.external('media') is None:
            raise CommandError('Media is on this server’s disk; there is nowhere to copy it.')
        local, remote = config.local_store(), config.store_for('media')
        copied = skipped = 0
        for item in local.list('', limit=100_000):
            if remote.exists(item.key):
                skipped += 1
                continue
            with open(local._path(item.key), 'rb') as handle:  # noqa: SLF001 - the local driver's own file
                remote.put_stream(item.key, handle, content_type=item.content_type)
            copied += 1
        self.stdout.write(f'Copied {copied} file(s); {skipped} were already there.')
