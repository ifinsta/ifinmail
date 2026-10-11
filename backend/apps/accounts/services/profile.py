"""Self-service profile writes (the services layer is the only model interface)."""

from __future__ import annotations

from django.utils.translation import gettext as _

from ..models import MailUser

MIN_PASSWORD_LENGTH = 8  # matches the registration flow's rule


class ProfileError(ValueError):
    """The requested change was refused (the message is safe to show)."""


class ProfileService:
    @staticmethod
    def set_full_name(user: MailUser, name: str) -> str:
        name = name.strip()[:128]
        if not name:
            raise ProfileError(_('Enter a display name.'))
        user.full_name = name
        user.save(update_fields=['full_name'])
        return name

    @staticmethod
    def change_password(user: MailUser, old_password: str, new_password: str) -> None:
        try:
            verified = bool(user.password) and user.check_password(old_password)
        except (ValueError, TypeError):
            verified = False
        if not verified:
            raise ProfileError(_('That current password is not correct.'))
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise ProfileError(
                _('A password needs at least %(count)s characters.')
                % {'count': MIN_PASSWORD_LENGTH}
            )
        user.set_password(new_password)
        # set_password fills both the Django hash and the Dovecot-compatible one.
        user.save(update_fields=['password', 'password_hash'])
