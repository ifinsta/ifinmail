"""Per-user session inspection and revocation (service layer).

Reads the Django session store and attributes sessions to a login via the
``_auth_user_id`` key. Only session metadata is ever exposed — never the full
session key, which would allow impersonation.
"""

from __future__ import annotations

import logging

from django.contrib.sessions.models import Session
from django.utils import timezone

from backend.apps.accounts.models import MailUser

from ..types.sessions import UserSession

logger = logging.getLogger('backend')

_KEY_HINT_CHARS = 8


class SessionError(ValueError):
    """A session request that cannot be fulfilled (message is user-safe)."""


def _user_id_matches(data: object, user: MailUser) -> bool:
    return isinstance(data, dict) and str(data.get('_auth_user_id', '')) == str(user.pk)


class UserSessionService:
    @staticmethod
    def list_for_user(user: MailUser, *, current_key: str | None = None) -> list[UserSession]:
        """All live sessions for ``user``, newest expiry first."""
        rows: list[UserSession] = []
        try:
            sessions = Session.objects.filter(expire_date__gt=timezone.now())
        except Exception:
            logger.exception('Could not list sessions for %s', user.email)
            return []
        for session in sessions:
            try:
                data = session.get_decoded()
            except Exception:
                continue
            if not _user_id_matches(data, user):
                continue
            key = session.session_key or ''
            rows.append(
                UserSession(
                    session_key=key,
                    key_hint=(key[:_KEY_HINT_CHARS] + '…') if key else '—',
                    expire_date=session.expire_date.isoformat() if session.expire_date else '',
                    is_current=bool(current_key and key == current_key),
                )
            )
        return sorted(rows, key=lambda r: r.expire_date, reverse=True)

    @staticmethod
    def revoke(user: MailUser, session_key: str) -> bool:
        """Delete one of ``user``'s sessions. Returns False when not found."""
        if not session_key:
            return False
        for session in Session.objects.filter(session_key=session_key):
            try:
                data = session.get_decoded()
            except Exception:
                continue
            if _user_id_matches(data, user):
                session.delete()
                return True
        return False

    @staticmethod
    def revoke_all(user: MailUser, *, except_key: str | None = None) -> int:
        """Delete all of ``user``'s sessions except ``except_key`` (never None-safe)."""
        killed = 0
        for row in UserSessionService.list_for_user(user):
            if except_key and row.session_key == except_key:
                continue
            if UserSessionService.revoke(user, row.session_key):
                killed += 1
        return killed

    @staticmethod
    def live_counts() -> dict[str, int]:
        """Live session count per user email (for the governance overview)."""
        from django.contrib.sessions.models import Session as _Session

        counts: dict[str, int] = {}
        try:
            sessions = _Session.objects.filter(expire_date__gt=timezone.now())
        except Exception:
            logger.exception('Could not count live sessions')
            return {}
        user_ids: set[str] = set()
        for session in sessions:
            try:
                data = session.get_decoded()
            except Exception:
                continue
            uid = data.get('_auth_user_id') if isinstance(data, dict) else None
            if uid:
                user_ids.add(str(uid))
        if not user_ids:
            return {}
        emails = {
            str(pk): email
            for pk, email in MailUser.objects.filter(pk__in=user_ids).values_list('pk', 'email')
        }
        for session in sessions:
            try:
                data = session.get_decoded()
            except Exception:
                continue
            uid = str(data.get('_auth_user_id', '')) if isinstance(data, dict) else ''
            email = emails.get(uid, '')
            if email:
                counts[email] = counts.get(email, 0) + 1
        return counts
