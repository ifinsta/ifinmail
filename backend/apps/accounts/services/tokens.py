"""API keys and tokens: scoped, expiring, rotatable (service layer).

A credential is a **key** (public identifier, safe to log: ``ifm_<12 chars>``) and a
**secret** (``ifs_<43 chars>``, shown once). Present them as HTTP Basic ``key:secret``, or as one
Bearer value ``ifm.<12 chars>.<secret>``. Only the SHA-256 hash of the secret is stored (it is
256 bits of randomness, so a slow hash adds nothing) and it is compared in constant time.

Effective power of a token call = token scopes ∩ the owner's *current*
permissions, so narrowing a user's role instantly narrows their tokens.
Tokens bypass interactive MFA by design (they are the machine credential);
expiry + rotation + per-token revocation, an optional network allow-list and a per-key rate limit
are the compensating controls. A rotation can keep the old secret alive for a short overlap so an
integration switches over without an outage.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
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
KEY_MARK = 'ifm_'  # a key id starts with this, so secret scanners and people can recognise it
SECRET_MARK = 'ifs_'
# Longest lifetime a token may be given; owners rotate rather than keep one for a year.
MAX_TOKEN_DAYS = 90
MAX_GRACE_HOURS = 168  # a rotated secret may overlap the new one for at most a week
MAX_NETWORKS = 20
MAX_SENDERS = 20
SEND_SCOPE = 'mail.send'
MAX_RATE_LIMIT = 6000
MAX_SEND_LIMIT = 100000  # recipients per day a key may be given
_PREFIX_CHARS = string.ascii_letters + string.digits
_PREFIX_LEN = 12
_USED_STAMP_EVERY = timedelta(seconds=60)  # last-used is written at most this often


class TokenError(ValueError):
    """A token request that cannot be fulfilled (message is user-safe)."""


@dataclass(frozen=True)
class VerifiedToken:
    user: MailUser
    row: APIToken


def _prefix() -> str:
    return ''.join(secrets.choice(_PREFIX_CHARS) for _ in range(_PREFIX_LEN))


def _secret() -> str:
    return SECRET_MARK + secrets.token_urlsafe(32)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def format_token(prefix: str, secret: str) -> str:
    return f'{_TOKEN_PREFIX}.{prefix}.{secret}'


def key_id(prefix: str) -> str:
    """The public key identifier shown to people and written to logs."""
    return f'{KEY_MARK}{prefix}'


def parse_key(value: str) -> str | None:
    """A key id (``ifm_<prefix>``, or the bare prefix) to the stored prefix, or None."""
    text = (value or '').strip()
    if text.startswith(KEY_MARK):
        text = text[len(KEY_MARK) :]
    if not text or len(text) > 16 or not all(c in _PREFIX_CHARS for c in text):
        return None
    return text


def normalize_networks(values: list[str] | None) -> list[str]:
    """Canonical CIDR strings; raises TokenError for anything that is not an address range."""
    cleaned: list[str] = []
    for raw in values or []:
        text = str(raw).strip()
        if not text:
            continue
        try:
            network = str(ipaddress.ip_network(text, strict=False))
        except ValueError as exc:
            raise TokenError(f'"{text}" is not an IP address or CIDR range.') from exc
        if network not in cleaned:
            cleaned.append(network)
    if len(cleaned) > MAX_NETWORKS:
        raise TokenError(f'Allow at most {MAX_NETWORKS} networks per key.')
    return cleaned


def normalize_senders(values: list[str] | None) -> list[str]:
    """Canonical sender entries: ``name@domain`` or ``*@domain``; raises TokenError otherwise.

    The domain of each entry must be hosted on this server (checked here, and again on every
    send, because a domain can be removed later).
    """
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    from backend.apps.domains.models import Domain

    cleaned: list[str] = []
    for raw in values or []:
        text = str(raw).strip().lower()
        if not text:
            continue
        local, _, domain = text.rpartition('@')
        if not domain or not local:
            raise TokenError(f'"{text}" is not an address. Use name@domain or *@domain.')
        if local != '*':
            try:
                validate_email(text)
            except ValidationError as exc:
                raise TokenError(f'"{text}" is not a valid address.') from exc
        if not Domain.objects.filter(name=domain).exists():
            raise TokenError(f'{domain} is not a domain on this server.')
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > MAX_SENDERS:
        raise TokenError(f'Allow at most {MAX_SENDERS} senders per key.')
    return cleaned


def sender_allowed(allowed: list[str] | None, address: str) -> bool:
    """True when ``address`` is one of the key's senders or on a ``*@domain`` entry."""
    wanted = (address or '').strip().lower()
    local, _, domain = wanted.rpartition('@')
    if not local or not domain:
        return False
    return any(entry == wanted or entry == f'*@{domain}' for entry in (allowed or []))


def address_allowed(networks: list[str] | None, address: str) -> bool:
    """True when the list is empty (anywhere) or the address lies in one of the ranges."""
    if not networks:
        return True
    try:
        ip = ipaddress.ip_address((address or '').strip())
    except ValueError:
        return False
    for text in networks:
        try:
            if ip in ipaddress.ip_network(text, strict=False):
                return True
        except ValueError:
            continue
    return False


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
    def list_all() -> list[APIToken]:
        """Every key on the server, newest first (the API keys page)."""
        return list(APIToken.objects.select_related('user').order_by('-created_at'))

    @staticmethod
    def get(token_id: str) -> APIToken | None:
        try:
            row: APIToken | None = (
                APIToken.objects.select_related('user').filter(pk=token_id).first()
            )
        except (ValueError, TypeError):  # not a UUID
            return None
        return row

    @staticmethod
    @transaction.atomic
    def create(
        user: MailUser,
        name: str,
        scopes: list[str],
        *,
        expires_in_days: int,
        allowed_networks: list[str] | None = None,
        rate_limit_per_minute: int | None = None,
        allowed_senders: list[str] | None = None,
        send_limit_per_day: int | None = None,
        sandbox: bool = False,
    ) -> tuple[APIToken, str]:
        """Create a token; returns ``(row, plaintext)`` — plaintext shown once."""
        clean_name = (name or '').strip()[:64]
        if not clean_name:
            raise TokenError('Give the token a name, e.g. "uptime monitor".')
        if expires_in_days <= 0 or expires_in_days > MAX_TOKEN_DAYS:
            raise TokenError(f'Expiry must be between 1 and {MAX_TOKEN_DAYS} days.')
        if rate_limit_per_minute is not None and not 1 <= rate_limit_per_minute <= MAX_RATE_LIMIT:
            raise TokenError(f'The rate limit must be between 1 and {MAX_RATE_LIMIT} per minute.')
        if send_limit_per_day is not None and not 1 <= send_limit_per_day <= MAX_SEND_LIMIT:
            raise TokenError(f'The daily sending limit must be between 1 and {MAX_SEND_LIMIT}.')
        networks = normalize_networks(allowed_networks)
        wanted = {str(scope) for scope in scopes or [] if str(scope) in TOKEN_SCOPES}
        if not wanted:
            raise TokenError('Pick at least one scope for the token.')
        # A token can never exceed its owner's current permissions.
        allowed = wanted & RoleService.effective_permissions(user)
        if not allowed:
            raise TokenError('None of those scopes are held by this login.')
        senders = normalize_senders(allowed_senders) if SEND_SCOPE in allowed else []
        if SEND_SCOPE in allowed and not senders:
            raise TokenError(
                'A key that can send mail must name the addresses it may send as '
                '(name@domain, or *@domain for a whole domain).'
            )
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
            allowed_networks=networks,
            rate_limit_per_minute=rate_limit_per_minute,
            allowed_senders=senders,
            send_limit_per_day=send_limit_per_day if SEND_SCOPE in allowed else None,
            sandbox=bool(sandbox),
        )
        return row, format_token(prefix, secret)

    @staticmethod
    def check(prefix: str, secret: str, address: str = '') -> tuple[VerifiedToken | None, str]:
        """Validate a key and secret. Returns ``(verified, '')`` or ``(None, reason)``.

        Reasons: ``unknown_key``, ``bad_secret``, ``expired``, ``owner_disabled``, ``network``.
        They are for the audit trail and logs; callers answer the client with one generic 401.
        """
        try:
            row = APIToken.objects.select_related('user').filter(prefix=prefix).first()
        except Exception:
            logger.exception('Token lookup failed')
            return None, 'unknown_key'
        if row is None:
            return None, 'unknown_key'
        now = timezone.now()
        presented = _digest(secret)
        current = hmac.compare_digest(row.token_hash, presented)
        overlap = bool(
            row.previous_hash
            and row.previous_expires_at is not None
            and row.previous_expires_at > now
            and hmac.compare_digest(row.previous_hash, presented)
        )
        if not (current or overlap):
            return None, 'bad_secret'
        if row.expires_at is not None and row.expires_at <= now:
            return None, 'expired'
        user = row.user
        if user is None or not user.is_active:
            return None, 'owner_disabled'
        if not address_allowed(row.allowed_networks, address):
            return None, 'network'
        stale = row.last_used_at is None or now - row.last_used_at >= _USED_STAMP_EVERY
        if stale or (address and row.last_used_ip != address):
            row.last_used_at = now
            row.last_used_ip = address or row.last_used_ip
            try:
                row.save(update_fields=['last_used_at', 'last_used_ip'])
            except Exception:
                logger.warning('Could not stamp token usage for %s', prefix)
        return VerifiedToken(user=user, row=row), ''

    @staticmethod
    def verify(value: str, address: str = '') -> VerifiedToken | None:
        """Validate the one-value Bearer wire format; None when anything is wrong."""
        split = split_token(value)
        if split is None:
            return None
        return TokenService.check(split[0], split[1], address)[0]

    @staticmethod
    @transaction.atomic
    def rotate(user: MailUser, token_id: str, *, grace_hours: int = 0) -> tuple[APIToken, str]:
        """Replace the secret, keeping prefix and scopes.

        With ``grace_hours`` the replaced secret keeps working for that long (never past the
        key's own expiry), so an integration can be switched over without an outage.
        """
        if not 0 <= grace_hours <= MAX_GRACE_HOURS:
            raise TokenError(f'The overlap must be between 0 and {MAX_GRACE_HOURS} hours.')
        row = APIToken.objects.filter(user=user, pk=token_id).first()
        if row is None:
            raise TokenError('That token no longer exists.')
        now = timezone.now()
        if grace_hours:
            until = now + timedelta(hours=grace_hours)
            if row.expires_at is not None:
                until = min(until, row.expires_at)
            row.previous_hash = row.token_hash
            row.previous_expires_at = until
        else:
            row.previous_hash = ''
            row.previous_expires_at = None
        secret = _secret()
        row.token_hash = _digest(secret)
        row.save(update_fields=['token_hash', 'previous_hash', 'previous_expires_at'])
        return row, format_token(row.prefix, secret)

    @staticmethod
    @transaction.atomic
    def revoke(user: MailUser, token_id: str) -> bool:
        """Delete one of ``user``'s tokens. Use counts as the audit trail."""
        deleted, _ = APIToken.objects.filter(user=user, pk=token_id).delete()
        return bool(deleted > 0)
