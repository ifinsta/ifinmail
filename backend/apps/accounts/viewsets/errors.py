"""Service errors to HTTP statuses, one place for every router.

Services raise ``ValueError`` subclasses whose message is safe to show. The API turns them into
a status the integration can act on; the message goes into ``detail`` unchanged.
"""

from __future__ import annotations

from ninja.errors import HttpError

_NOT_FOUND = ('does not exist', 'no longer exists', 'no login exists', 'unknown domain')
_CONFLICT = ('already',)


def problem(exc: Exception) -> HttpError:
    """403 for a protected resource, 404 when it is not there, 409 for a clash, else 422."""
    from backend.apps.mail.types.provisioning import MailboxProtectedError

    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, MailboxProtectedError):
        return HttpError(403, text)
    if any(marker in lowered for marker in _NOT_FOUND):
        return HttpError(404, text)
    if any(marker in lowered for marker in _CONFLICT):
        return HttpError(409, text)
    return HttpError(422, text)


__all__ = ['problem']
