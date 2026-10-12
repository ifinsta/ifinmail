"""Validate a plugin manifest and print every problem (exit 1 when invalid)."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.types import ManifestError


class Command(BaseCommand):
    help = 'Validate a plugin.toml against manifest_version 1 and the registered extension points.'

    def add_arguments(self, parser: object) -> None:
        parser.add_argument('path', help='Path to plugin.toml')

    def handle(self, *args: object, **options: object) -> None:
        path = Path(str(options['path']))
        try:
            manifest = manifests.load(path.read_bytes())
        except OSError as exc:
            raise CommandError(f'cannot read {path}: {exc}') from None
        except ManifestError as exc:
            for location, message in exc.problems:
                self.stderr.write(f'  {location}: {message}')
            raise CommandError(f'{len(exc.problems)} problem(s) in {path}') from None
        self.stdout.write(
            self.style.SUCCESS(f'{manifest.id} {manifest.version} is valid ({manifest.name}).')
        )
