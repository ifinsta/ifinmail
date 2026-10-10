"""Whether first-run setup is finished.

Setup is complete once an administrator finishes (or skips) the wizard, which
records a flag, or once any mailbox exists (installs that predate the flag).
A staff login alone does NOT mean setup is complete: the bootstrap script
creates one so that the wizard can be opened at all.
"""

from __future__ import annotations

import logging

from django.db.utils import DatabaseError

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

logger = logging.getLogger('backend')


class SetupState:
    @staticmethod
    def is_complete() -> bool:
        try:
            if SystemSettings.get_bool(SettingKey.SETUP_COMPLETED, False):
                return True
            from backend.apps.mail.models import Mailbox

            return Mailbox.objects.exists()
        except DatabaseError:
            logger.warning('Database not ready for the setup check')
            return False

    @staticmethod
    def is_marked_complete() -> bool:
        """True only once an administrator finished or skipped the wizard.

        The wizard's own pages use this (not ``is_complete``) so that creating the first
        mailbox does not throw the person out before they reach the final step.
        """
        try:
            return SystemSettings.get_bool(SettingKey.SETUP_COMPLETED, False)
        except DatabaseError:
            return False

    @staticmethod
    def mark_complete() -> None:
        SystemSettings.set(SettingKey.SETUP_COMPLETED, True)
