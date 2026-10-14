"""Break-glass: let a login use its password for the console again.

For a login that switched to passkeys-only sign-in and has lost every passkey and recovery code.
Needs shell access to the server, which is the trust boundary for this action. The person's
passkeys are kept; they can switch passkeys-only back on. Every use is written to the audit trail.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.passwordless import PasswordlessService
from backend.apps.core.platform.services.audit import AuditService


class Command(BaseCommand):
    help = 'Allow console password sign-in again for one login (passkeys-only recovery).'

    def add_arguments(self, parser: object) -> None:
        parser.add_argument('email', help='Address of the login')

    def handle(self, *args: object, **options: object) -> None:
        email = str(options['email']).strip().lower()
        user = MailUser.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f'No login for {email}.')
        changed = PasswordlessService.disable(user)
        AuditService.record(
            action='passkeys_only_reset_cli',
            user='server-shell',
            detail=email,
            severity='warning',
        )
        if changed:
            self.stdout.write(
                self.style.SUCCESS(f'{email} can sign in to the console with its password again.')
            )
        else:
            self.stdout.write(f'{email} was not using passkeys-only sign-in; nothing changed.')
