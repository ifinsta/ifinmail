"""First-party API tokens: scoped, expiring, rotatable (service layer).

Wire format: ``ifm.<12-char prefix>.<secret>``. Only the SHA-256 hash of the
secret is stored; the plaintext is returned once at creation/rotation.

Effective power of a token call = token scopes ∩ the owner's *current*
permissions, so narrowing a user's role instantly narrows their tokens.
Tokens bypass interactive MFA by design (they are the machine credential);
expiry + rotation + per-token revocation are the compensating controls.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import string
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from backend.apps.accounts.models import APIToken, MailUser
from backend.apps.accounts.types.permissions import TOKEN_SCOPES

from .roles import RoleService

logger = logging.getLogger('backend')

_TOKEN_PREFIX = 'ifm'
_PREFIX_CHARS = string.ascii_letters + string.digits
_PREFIX_LEN = 12


class TokenError(ValueError):
    """A token request that cannot be fulfilled (message is user-safe)."""


@dataclass(frozen=True)
class VerifiedToken:
    user: MailUser
    row: APIToken


def _prefix() -> str:
    return ''.join(secrets.choice(_PREFIX_CHARS) for _ in range(_PREFIX_LEN))


def _secret() -> str:
    return secrets.token_urlsafe(32)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def format_token(prefix: str, secret: str) -> str:
    return f'{_TOKEN_PREFIX}.{prefix}.{secret}'


def split_token(value: str) -> tuple[str, str] | None:
    """Split wire format into ``(prefix, secret)`` or None when malformed."""
    parts = (value or '').strip().split('.')
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


class TokenService:
    @staticmethod
    def list_for(user: MailUser) -> list[APIToken]:
        return list(APIToken.objects.filter(user=user).order_by('-created_at'))

    @staticmethod
    @transaction.atomic
    def create(
        user: MailUser,
        name: str,
        scopes: list[str],
        *,
        expires_in_days: int,
    ) -> tuple[APIToken, str]:
        """Create a token; returns ``(row, plaintext)`` — plaintext shown once."""
        clean_name = (name or '').strip()[:64]
        if not clean_name:
            raise TokenError('Give the token a name, e.g. "uptime monitor".')
        if expires_in_days <= 0 or expires_in_days > 365:
            raise TokenError('Expiry must be between 1 and 365 days.')
        wanted = {str(scope) for scope in scopes or [] if str(scope) in TOKEN_SCOPES}
        if not wanted:
            raise TokenError('Pick at least one scope for the token.')
        # A token can never exceed its owner's current permissions.
        allowed = wanted & RoleService.effective_permissions(user)
        if not allowed:
            raise TokenError('None of those scopes are held by this login.')
        for _ in range(5):
            prefix = _prefix()
            if not APIToken.objects.filter(prefix=prefix).exists():
                break
        else:
            raise TokenError('Could not mint a unique token. Try again.')
        secret = _secret()
        row = APIToken.objects.create(
            user=user,
            name=clean_name,
            prefix=prefix,
            token_hash=_digest(secret),
            scopes=sorted(allowed),
            expires_at=timezone.now() + timedelta(days=expires_in_days),
        )
        return row, format_token(prefix, secret)

    @staticmethod
    def verify(value: str) -> VerifiedToken | None:
        """Validate wire format; returns the owner + row or None (no exceptions)."""
        split = split_token(value)
        if split is None:
            return None
        prefix, secret = split
        try:
            row = APIToken.objects.select_related('user').filter(prefix=prefix).first()
        except Exception:
            logger.exception('Token lookup failed')
            return None
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at <= timezone.now():
            return None
        user = row.user
        if user is None or not user.is_active:
            return None
        if row.token_hash != _digest(secret):
            return None
        row.last_used_at = timezone.now()
        try:
            row.save(update_fields=['last_used_at'])
        except Exception:
            logger.warning('Could not stamp token usage for %s', prefix)
        return VerifiedToken(user=user, row=row)

    @staticmethod
    @transaction.atomic
    def rotate(user: MailUser, token_id: str) -> tuple[APIToken, str]:
        """Replace the secret, keeping prefix/scopes (old secret dies now)."""
        row = APIToken.objects.filter(user=user, pk=token_id).first()
        if row is None:
            raise TokenError('That token no longer exists.')
        secret = _secret()
        row.token_hash = _digest(secret)
        row.save(update_fields=['token_hash'])
        return row, format_token(row.prefix, secret)

    @staticmethod
    @transaction.atomic
    def revoke(user: MailUser, token_id: str) -> bool:
        """Delete one of ``user``'s tokens. Use counts as the audit trail."""
        deleted, _ = APIToken.objects.filter(user=user, pk=token_id).delete()
        return deleted > 0
