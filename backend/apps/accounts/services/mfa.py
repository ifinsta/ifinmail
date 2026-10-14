"""Two-factor authentication (TOTP + recovery codes), service layer.

Single interface for all MFA state. Deliberately stdlib-only (RFC 6238 TOTP
is ~30 lines): no new third-party dependency for the login path.

Layout of responsibilities:
* secret plaintext exists only transiently — returned once at enrollment,
  Fernet-encrypted (bound to ``mfa-totp:`` + Django SECRET_KEY) at rest;
* only recovery-code *hashes* are stored; codes are single-use;
* every state change is audited by the caller (views), not here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import struct
import time
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from backend.apps.accounts.models import MFARecoveryCode, TOTPDevice

logger = logging.getLogger('backend')

_STEP_SECONDS = 30
_DIGITS = 6
_ALLOWED_DRIFT_STEPS = 1
_SECRET_BYTES = 20
_RECOVERY_CODE_COUNT = 10
_RECOVERY_CODE_BYTES = 10


class MFAError(ValueError):
    """An MFA request that cannot be fulfilled (message is user-safe)."""


# -- TOTP core (RFC 6238, SHA-1, 30s steps) ----------------------------------


def _counter(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // _STEP_SECONDS)


def _hotp(secret: bytes, counter: int) -> str:
    mac = hmac.new(secret, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack('>I', mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**_DIGITS)).zfill(_DIGITS)


def generate_secret() -> str:
    """A fresh base32 TOTP secret (plaintext — encrypt before storing)."""
    return base64.b32encode(secrets.token_bytes(_SECRET_BYTES)).decode()


def provisioning_uri(secret: str, account: str, issuer: str = '') -> str:
    """The authenticator app shows ``issuer`` (the brand name by default) next to the account."""
    from urllib.parse import quote

    from backend.config.branding import brand_name

    account = account.strip()
    label = quote(issuer or brand_name(), safe='')
    return (
        f'otpauth://totp/{label}:{quote(account, safe="@")}'
        f'?secret={secret}&issuer={label}&algorithm=SHA1&digits=6&period=30'
    )


def verify_code(secret: str, code: str, *, at: float | None = None) -> bool:
    """True when ``code`` matches the current step (±1 step of drift)."""
    try:
        raw = base64.b32decode(secret.strip().upper())
    except Exception:
        return False
    text = (code or '').strip().replace(' ', '')
    if not text.isdigit():
        return False
    step = _counter(at)
    for candidate in (step - _ALLOWED_DRIFT_STEPS, step, step + _ALLOWED_DRIFT_STEPS):
        if candidate < 0:
            continue
        if hmac.compare_digest(_hotp(raw, candidate), text.zfill(_DIGITS)[-_DIGITS:]):
            return True
    return False


# -- secret encryption ----------------------------------------------------------


def _fernet() -> Fernet:
    """Cipher for stored TOTP secrets, derived from the Django secret key."""
    from django.conf import settings

    seed = f'mfa-totp:{settings.SECRET_KEY}'.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


def _encrypt_secret(secret: str) -> str:
    return 'fernet:' + _fernet().encrypt(secret.encode()).decode()


def _decrypt_secret(stored: str) -> str:
    if not stored.startswith('fernet:'):
        raise MFAError('This device was stored in an unknown format.')
    try:
        return _fernet().decrypt(stored[len('fernet:') :].encode()).decode()
    except InvalidToken as exc:
        raise MFAError('This device cannot be decrypted with the current secret key.') from exc


# -- service ---------------------------------------------------------------------


class TOTPService:
    REMIND_AFTER_DAYS = 7

    @staticmethod
    def enforced() -> bool:
        """True when policy makes two-factor mandatory for console logins (MFA_ENFORCEMENT)."""
        from django.conf import settings

        return str(getattr(settings, 'MFA_ENFORCEMENT', 'optional')).strip().lower() == 'required'

    @staticmethod
    def prompt_due(user: object) -> bool:
        """Should this console login be sent to two-factor enrollment now?

        Under the default (optional) policy two-factor is offered, not forced: not once it is
        set up, not when the login turned it off, and not while a "Remind me in a week" is
        running. Under the ``required`` policy only a verified device ends the prompt.
        """
        if TOTPService.enforced():
            return not TOTPService.has_second_factor(user)
        if not getattr(user, 'mfa_required', True):
            return False
        remind_after = getattr(user, 'mfa_remind_after', None)
        if remind_after is not None and timezone.now() < remind_after:
            return False
        return not TOTPService.has_second_factor(user)

    @staticmethod
    def snooze(user: object, days: int | None = None) -> None:
        """Stop prompting this login for two-factor setup for ``days`` (default a week)."""
        if TOTPService.enforced():
            raise MFAError('Two-factor sign-in is required by your administrator.')
        user.mfa_remind_after = timezone.now() + timedelta(days=days or TOTPService.REMIND_AFTER_DAYS)
        user.save(update_fields=['mfa_remind_after'])

    @staticmethod
    def has_verified_device(user: object) -> bool:
        return TOTPDevice.objects.filter(user=user, verified=True).exists()

    @staticmethod
    def has_second_factor(user: object) -> bool:
        """True when a password sign-in is followed by a second step: a verified authenticator.

        A passkey is deliberately not counted. It is an alternative to the email and password
        (it replaces them, and a passkey sign-in is already two factors in one gesture), so
        holding one does not make a *password* sign-in any stronger and must not add a step to it.
        """
        return TOTPService.has_verified_device(user)

    @staticmethod
    def passkey_count(user: object) -> int:
        from backend.apps.accounts.models import Passkey

        return Passkey.objects.filter(user=user).count()

    @staticmethod
    def pending_device(user: object) -> TOTPDevice | None:
        return TOTPDevice.objects.filter(user=user, verified=False).order_by('-created_at').first()

    @staticmethod
    @transaction.atomic
    def start_enrollment(user: object, name: str = 'Authenticator app') -> tuple[str, str]:
        """Create a pending device; returns ``(otpauth_uri, recovery_preview)``.

        The plaintext secret is embedded in the URI and never stored — the
        caller shows it once. Any older pending device is replaced.
        """
        TOTPDevice.objects.filter(user=user, verified=False).delete()
        secret = generate_secret()
        TOTPDevice.objects.create(
            user=user,
            name=(name or 'Authenticator app')[:64],
            secret_encrypted=_encrypt_secret(secret),
        )
        email = getattr(user, 'email', '')
        return provisioning_uri(secret, email), secret

    @staticmethod
    @transaction.atomic
    def confirm_enrollment(user: object, code: str, *, at: float | None = None) -> list[str]:
        """Activate the pending device after one correct code.

        Returns fresh recovery codes (plaintext, show once) on activation.
        """
        device = TOTPService.pending_device(user)
        if device is None:
            raise MFAError('No authenticator setup is in progress. Start again.')
        secret = _decrypt_secret(device.secret_encrypted)
        if not verify_code(secret, code, at=at):
            raise MFAError('That code did not match. Check the time on your device.')
        now = timezone.now()
        device.verified = True
        device.verified_at = now
        device.last_used_at = now
        device.save(update_fields=['verified', 'verified_at', 'last_used_at'])
        # Single active device: the just-proven one replaces any older device.
        TOTPDevice.objects.filter(user=user, verified=True).exclude(pk=device.pk).delete()
        # Holding a verified factor again re-arms enforcement for this login.
        if not user.mfa_required:
            user.mfa_required = True
            user.save(update_fields=['mfa_required'])
        return TOTPService.fresh_recovery_codes(user)

    @staticmethod
    @transaction.atomic
    def disable_second_factor(user: object, code: str) -> None:
        """Turn two-factor off for this login, after proving possession of it.

        The code may come from the authenticator or be a recovery code (it is
        consumed either way). Devices and codes are removed and enforcement is
        relaxed until the user enrolls again.
        """
        if TOTPService.enforced():
            raise MFAError('Two-factor sign-in is required by your administrator.')
        TOTPService.verify_login(user, code)  # raises MFAError when it does not match
        TOTPService.reset(user)
        user.mfa_required = False
        user.save(update_fields=['mfa_required'])

    @staticmethod
    @transaction.atomic
    def fresh_recovery_codes(user: object) -> list[str]:
        """Replace all codes; returns the new plaintext set (show once)."""
        MFARecoveryCode.objects.filter(user=user).delete()
        plain: list[str] = []
        for _ in range(_RECOVERY_CODE_COUNT):
            code = secrets.token_urlsafe(_RECOVERY_CODE_BYTES)[:16]
            plain.append(code)
            MFARecoveryCode.objects.create(user=user, code_hash=make_password(code))
        return plain

    @staticmethod
    def verify_login(user: object, code: str, *, at: float | None = None) -> str:
        """Check a login-time code. Returns 'totp' or 'recovery' on success."""
        text = (code or '').strip().replace(' ', '')
        if not text:
            raise MFAError('Enter the code from your authenticator app.')
        for device in TOTPDevice.objects.filter(user=user, verified=True):
            try:
                secret = _decrypt_secret(device.secret_encrypted)
            except MFAError:
                logger.exception('TOTP device undecryptable for %s', getattr(user, 'email', '?'))
                continue
            if verify_code(secret, text, at=at):
                device.last_used_at = timezone.now()
                device.save(update_fields=['last_used_at'])
                return 'totp'
        row = TOTPService._consume_recovery_code(user, text)
        if row is not None:
            return 'recovery'
        raise MFAError('That code did not match. Try again.')

    @staticmethod
    @transaction.atomic
    def _consume_recovery_code(user: object, text: str) -> MFARecoveryCode | None:
        for row in MFARecoveryCode.objects.filter(user=user, used=False):
            if check_password(text, row.code_hash):
                row.used = True
                row.used_at = timezone.now()
                row.save(update_fields=['used', 'used_at'])
                return row
        return None

    @staticmethod
    def remaining_recovery_codes(user: object) -> int:
        return MFARecoveryCode.objects.filter(user=user, used=False).count()

    @staticmethod
    @transaction.atomic
    def reset(user: object) -> None:
        """Remove all devices and codes (admin-assisted recovery)."""
        TOTPDevice.objects.filter(user=user).delete()
        MFARecoveryCode.objects.filter(user=user).delete()

    @staticmethod
    def status_for(user: object) -> dict[str, object]:
        """Summary for profile/admin display (never includes secrets)."""
        devices = list(TOTPDevice.objects.filter(user=user, verified=True))
        return {
            'enabled': bool(devices),
            'devices': [
                {
                    'name': d.name,
                    'verified_at': d.verified_at.isoformat() if d.verified_at else '',
                    'last_used_at': d.last_used_at.isoformat() if d.last_used_at else '',
                }
                for d in devices
            ],
            'recovery_remaining': TOTPService.remaining_recovery_codes(user),
            'pending': TOTPService.pending_device(user) is not None,
            'enforced': TOTPService.enforced(),
            'passkeys': TOTPService.passkey_count(user),
        }
