"""The administrator the installer creates, and replacing its printed password.

The installer generates the first administrator's password, prints it in the terminal and keeps
it in provisioning/.env. That login is flagged ``password_change_required`` so the console asks
for a new password at first sign-in, before anything else (MFA enrollment comes after).
"""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext as _

from ..models import MailUser
from .profile import MIN_PASSWORD_LENGTH, ProfileError


class InitialAdminService:
    @staticmethod
    @transaction.atomic
    def ensure(email: str, password: str) -> tuple[MailUser, bool]:
        """Create the installer's administrator unless it exists. Returns (user, created).

        An existing login is never touched: its password may already have been changed.
        """
        email = MailUser.objects.normalize_email(email.strip())
        existing = MailUser.objects.filter(email=email).first()
        if existing is not None:
            return existing, False
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ProfileError(
                _('A password needs at least %(count)s characters.')
                % {'count': MIN_PASSWORD_LENGTH}
            )
        user = MailUser.objects.create_superuser(
            email, password, password_change_required=True
        )
        return user, True

    @staticmethod
    def set_first_password(user: MailUser, new_password: str, confirm: str) -> None:
        """Replace the installer's password. The person just signed in with it, so the
        current password is not asked again."""
        if new_password != confirm:
            raise ProfileError(_('The two passwords do not match.'))
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise ProfileError(
                _('A password needs at least %(count)s characters.')
                % {'count': MIN_PASSWORD_LENGTH}
            )
        if user.check_password(new_password):
            raise ProfileError(_('Choose a password different from the one the installer printed.'))
        user.set_password(new_password)
        user.password_change_required = False
        # set_password fills both the Django hash and the Dovecot-compatible one.
        user.save(update_fields=['password', 'password_hash', 'password_change_required'])
