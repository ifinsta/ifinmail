"""Passkeys-only sign-in to the console: the password stops opening it.

A person who holds passkeys can switch their own console sign-in to passkeys only. Then the email
and password no longer open the console for that login, so a stolen or guessed password is worth
nothing there. What this does *not* touch is the mailbox password: mail apps sign in to IMAP and
SMTP with it, and that has to keep working.

The danger is lockout, so the switch is guarded and has three ways back:

* it can only be turned on with enough passkeys that losing one device is survivable (two, or one
  that syncs across the person's devices), and it hands out single-use **recovery codes** at that
  moment;
* the last passkeys cannot be removed while it is on;
* an administrator (Mailboxes → profile) or the server shell (``make allow-password-login``) can
  switch password sign-in back on.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from backend.apps.accounts.models import MailUser, Passkey, PasskeyRecoveryCode, UserProfile

CODE_COUNT = 10
_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'  # no 0/o/1/l/i: codes are read off a screen or paper
_GROUPS, _GROUP_LEN = 4, 4  # xxxx-xxxx-xxxx-xxxx: 16 symbols, about 79 bits


class PasswordlessError(Exception):
    """The switch cannot be changed now; the message says why."""


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str
    passkeys: int
    synced: int


def _normalise(code: str) -> str:
    return ''.join(ch for ch in (code or '').lower() if ch.isalnum())


def _new_code() -> str:
    raw = ''.join(secrets.choice(_ALPHABET) for _ in range(_GROUPS * _GROUP_LEN))
    return '-'.join(raw[i : i + _GROUP_LEN] for i in range(0, len(raw), _GROUP_LEN))


class PasswordlessService:
    # -- state -----------------------------------------------------------------------------

    @staticmethod
    def is_passwordless(user: MailUser) -> bool:
        return UserProfile.objects.filter(user=user, password_login_disabled=True).exists()

    @staticmethod
    def remaining_codes(user: MailUser) -> int:
        return PasskeyRecoveryCode.objects.filter(user=user, used_at__isnull=True).count()

    @staticmethod
    def eligibility(user: MailUser, *, without: object | None = None) -> Eligibility:
        """Whether the person holds enough passkeys to rely on them alone.

        ``without`` is a passkey id to leave out, for judging a removal before it happens.
        """
        queryset = Passkey.objects.filter(user=user)
        if without is not None:
            queryset = queryset.exclude(pk=without)
        flags = list(queryset.values_list('backup_eligible', flat=True))
        total, synced = len(flags), sum(1 for flag in flags if flag)
        if total >= 2 or (total >= 1 and synced >= 1):
            return Eligibility(True, '', total, synced)
        if total == 0:
            reason = 'Add a passkey first.'
        else:
            reason = (
                'Add a second passkey (another device or a security key), or use one that syncs '
                'across your devices, so losing this device cannot lock you out.'
            )
        return Eligibility(False, reason, total, synced)

    # -- switching -------------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def enable(user: MailUser) -> list[str]:
        """Turn password sign-in to the console off; returns the recovery codes (show once)."""
        verdict = PasswordlessService.eligibility(user)
        if not verdict.ok:
            raise PasswordlessError(verdict.reason)
        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.password_login_disabled = True
        profile.save(update_fields=['password_login_disabled'])
        return PasswordlessService._issue_codes(user)

    @staticmethod
    @transaction.atomic
    def disable(user: MailUser) -> bool:
        """Allow the password for the console again. Returns whether anything changed."""
        changed = UserProfile.objects.filter(user=user, password_login_disabled=True).update(
            password_login_disabled=False
        )
        PasskeyRecoveryCode.objects.filter(user=user).delete()
        return bool(changed)

    @staticmethod
    @transaction.atomic
    def new_codes(user: MailUser) -> list[str]:
        if not PasswordlessService.is_passwordless(user):
            raise PasswordlessError('Recovery codes exist only while passkeys-only is on.')
        return PasswordlessService._issue_codes(user)

    @staticmethod
    def _issue_codes(user: MailUser) -> list[str]:
        PasskeyRecoveryCode.objects.filter(user=user).delete()
        codes = [_new_code() for _ in range(CODE_COUNT)]
        PasskeyRecoveryCode.objects.bulk_create(
            [PasskeyRecoveryCode(user=user, code_hash=make_password(_normalise(c))) for c in codes]
        )
        return codes

    # -- the way back in --------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def consume_code(user: MailUser, code: str) -> bool:
        """Spend one recovery code. Only a login with password sign-in switched off has any."""
        text = _normalise(code)
        if len(text) != _GROUPS * _GROUP_LEN:
            return False
        for row in PasskeyRecoveryCode.objects.select_for_update().filter(
            user=user, used_at__isnull=True
        ):
            if check_password(text, row.code_hash):
                row.used_at = timezone.now()
                row.save(update_fields=['used_at'])
                return True
        return False

    @staticmethod
    def can_remove_passkey(user: MailUser, passkey_id: object) -> Eligibility:
        """While the switch is on, removing a passkey must leave enough of them."""
        if not PasswordlessService.is_passwordless(user):
            return Eligibility(True, '', 0, 0)
        verdict = PasswordlessService.eligibility(user, without=passkey_id)
        if verdict.ok:
            return verdict
        return Eligibility(
            False,
            'Passkeys-only sign-in is on, and removing this passkey would leave too few to rely '
            'on. Add another passkey first, or turn passkeys-only sign-in off.',
            verdict.passkeys,
            verdict.synced,
        )
