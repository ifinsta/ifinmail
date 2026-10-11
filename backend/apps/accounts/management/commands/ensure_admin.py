"""Create the installer's administrator (DJANGO_SUPERUSER_EMAIL / _PASSWORD) if missing.

Run by the api entrypoint on every start. Idempotent: an existing login is left alone. A newly
created administrator must choose a new password at first sign-in.
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from backend.apps.accounts.services.initial_admin import InitialAdminService
from backend.apps.accounts.services.profile import ProfileError


class Command(BaseCommand):
    help = 'Create the first administrator from the environment; it must change its password.'

    def handle(self, *args, **options) -> None:
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '').strip()
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
        if not email or not password:
            self.stdout.write('DJANGO_SUPERUSER_EMAIL or _PASSWORD not set; no administrator created.')
            return
        try:
            user, created = InitialAdminService.ensure(email, password)
        except ProfileError as exc:
            raise CommandError(str(exc)) from exc
        if created:
            self.stdout.write(f'Created administrator {user.email} (new password required at first sign-in).')
        else:
            self.stdout.write(f'Administrator {user.email} already exists.')
