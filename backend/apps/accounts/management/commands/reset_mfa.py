"""Break-glass: remove a login's second factor from the server shell.

Needs shell access to the server, which is the trust boundary for this action. Use it when the only
administrator has lost both their authenticator and their recovery codes; the person enrolls again
at next sign-in. Every use is written to the audit trail.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.mfa import TOTPService
from backend.apps.core.platform.services.audit import AuditService


class Command(BaseCommand):
    help = 'Remove the second factor (devices and recovery codes) for one login.'

    def add_arguments(self, parser: object) -> None:
        parser.add_argument('email', help='Address of the login to reset')

    def handle(self, *args: object, **options: object) -> None:
        email = str(options['email']).strip().lower()
        user = MailUser.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f'No login for {email}.')
        TOTPService.reset(user)
        AuditService.record(
            action='mfa_reset_cli',
            user='server-shell',
            detail=email,
            severity='warning',
        )
        self.stdout.write(
            self.style.SUCCESS(f'Second factor removed for {email}; they enroll again at sign-in.')
        )
