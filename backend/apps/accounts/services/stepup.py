"""Password re-confirmation for the actions that change who can do what.

A stolen session or an unattended console must not be enough to hand out admin rights,
mint an API token or delete a mailbox. These actions ask for the signed-in person's own
password again; wrong attempts are limited and audited.
"""

from __future__ import annotations

from django.core.cache import cache
from django.http import HttpRequest

from backend.apps.core.platform.services.audit import AuditService

FIELD = 'confirm_password'
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 600


class StepUpService:
    @staticmethod
    def confirm(request: HttpRequest) -> str | None:
        """Return ``None`` when the posted password is the signed-in user's, else a message."""
        user = request.user
        key = f'stepup_attempts:{user.pk}'
        attempts = cache.get(key, 0)
        if attempts >= MAX_ATTEMPTS:
            return 'Too many wrong passwords. Wait ten minutes and try again.'
        password = request.POST.get(FIELD, '')
        if not password:
            return 'Enter your password to confirm this change.'
        if user.check_password(password):
            cache.delete(key)
            return None
        cache.set(key, attempts + 1, WINDOW_SECONDS)
        AuditService.record(
            action='stepup_failed',
            user=user.email,
            detail=request.path,
            severity='warning',
        )
        return 'That password is not correct.'
