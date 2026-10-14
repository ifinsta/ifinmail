"""Publish (or list) app releases from the command line.

Examples::

    python manage.py publish_release app-release.apk --notes "Faster sync"
    python manage.py publish_release app-release.apk --channel beta --rollout 20
    python manage.py publish_release app-release.apk --no-publish   # upload, offer later
    python manage.py publish_release --list

The same checks run as for the console and the API: right application, signed, new version code,
same signing key as before. The file is read from disk, so run it where the file is (inside the
``api`` container, or pipe it in with ``docker compose cp``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError, CommandParser

from backend.apps.core.releases.services import ReleaseService
from backend.apps.core.releases.types import CHANNEL_VALUES, DEFAULT_CHANNEL, Platform


class Command(BaseCommand):
    help = 'Publish an Android build to devices, or list the releases on record.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('apk', nargs='?', help='Path of the signed APK to publish.')
        parser.add_argument('--list', action='store_true', help='List releases and exit.')
        parser.add_argument('--channel', default=DEFAULT_CHANNEL, choices=CHANNEL_VALUES)
        parser.add_argument('--notes', default='', help='What is new (Markdown).')
        parser.add_argument('--notes-file', help='Read the notes from a file instead.')
        parser.add_argument('--rollout', type=int, default=100, help='Percent of devices (0-100).')
        parser.add_argument('--mandatory', action='store_true', help='Force older installs to update.')
        parser.add_argument('--no-publish', action='store_true', help='Store it but do not offer it.')
        parser.add_argument('--actor', default='cli', help='Name recorded in the audit trail.')

    def handle(self, *args: Any, **options: Any) -> None:
        platform = Platform.ANDROID.value
        if options['list']:
            self._list(platform)
            return
        if not options['apk']:
            raise CommandError('Give the path of an APK, or use --list.')
        path = Path(options['apk'])
        if not path.is_file():
            raise CommandError(f'{path} is not a file.')
        notes = options['notes']
        if options['notes_file']:
            notes = Path(options['notes_file']).read_text(encoding='utf-8')
        upload = SimpleUploadedFile(
            path.name, path.read_bytes(), content_type='application/vnd.android.package-archive'
        )
        try:
            release = ReleaseService.publish(
                upload=upload,
                platform=platform,
                channel=options['channel'],
                notes=notes,
                mandatory=options['mandatory'],
                rollout_percent=options['rollout'],
                publish=not options['no_publish'],
                actor=options['actor'],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        state = 'published' if release.is_published else 'stored (not offered yet)'
        self.stdout.write(
            self.style.SUCCESS(
                f'{release.version_name} (build {release.version_code}) {state} on the '
                f'{release.channel} channel, {release.size_bytes} bytes, sha256 {release.sha256}'
            )
        )

    def _list(self, platform: str) -> None:
        rows = ReleaseService.list_releases(platform)
        if not rows:
            self.stdout.write('No releases yet.')
            return
        for r in rows:
            flags = [
                'live' if r.is_published else 'withdrawn',
                *(['mandatory'] if r.mandatory else []),
                *([f'{r.rollout_percent}%'] if r.rollout_percent < 100 else []),
            ]
            self.stdout.write(
                f'{r.version_code:>6}  {r.version_name:<14} {r.channel:<7} '
                f'{r.size_bytes:>10}  {", ".join(flags)}'
            )
