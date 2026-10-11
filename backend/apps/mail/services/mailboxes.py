"""Mailbox and alias management.

A mailbox is three things that must stay in step: a ``mailboxes`` row (Postfix
accepts mail for it), a ``users`` row (Dovecot and the console authenticate
against it) and, for the person using it, a password. These services create and
remove them together in one transaction so they cannot drift apart.
"""

from __future__ import annotations

import logging
import re

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from backend.apps.accounts.models import MailUser
from backend.apps.domains.models import Domain

from ..models import Alias, Mailbox
from ..types.provisioning import AliasRow, MailboxError, MailboxRow
from ..types.quota import DEFAULT_QUOTA_BYTES
from ..types.reserved import RESERVED_LOCAL_PARTS

logger = logging.getLogger('backend')

_LOCAL_PART_RE = re.compile(r'^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$')
_MAX_ADDRESS = 128  # aliases.source is VARCHAR(128)
MIN_PASSWORD_LENGTH = 8


def split_address(address: str) -> tuple[str, str]:
    local, _, domain = address.strip().lower().partition('@')
    if not local or not domain:
        raise MailboxError('Enter a full address such as name@example.com.')
    return local, domain


def validate_local_part(local_part: str, *, reserved_blocked: bool = False) -> str:
    local_part = local_part.strip().lower()
    if not _LOCAL_PART_RE.match(local_part):
        raise MailboxError(
            'Use 1-64 letters, numbers, dots, hyphens, underscores or plus signs; '
            'start and end with a letter or number.'
        )
    if '..' in local_part:
        raise MailboxError('A name cannot contain two dots in a row.')
    if reserved_blocked and local_part in RESERVED_LOCAL_PARTS:
        raise MailboxError('This name is reserved and cannot be used.')
    return local_part


def _validate_password(password: str, email: str = '') -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise MailboxError(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.')
    try:
        validate_password(password, user=MailUser(email=email) if email else None)
    except ValidationError as exc:
        raise MailboxError(' '.join(exc.messages)) from exc


def _get_domain(name: str) -> Domain:
    domain = Domain.objects.filter(name=name.strip().lower()).first()
    if domain is None:
        raise MailboxError(f'{name} is not a domain on this server. Add it first.')
    return domain


class MailboxService:
    @staticmethod
    def address_for(mailbox: Mailbox) -> str:
        return f'{mailbox.local_part}@{mailbox.domain.name}'

    @staticmethod
    def mailbox_id_for(address: str) -> str | None:
        """Mailbox id for ``address``, or None when there is no such mailbox."""
        local, domain = split_address(address)
        mailbox = Mailbox.objects.filter(local_part=local, domain__name=domain).first()
        return str(mailbox.id) if mailbox is not None else None

    @staticmethod
    def exists(address: str) -> bool:
        local, domain = split_address(address)
        return Mailbox.objects.filter(local_part=local, domain__name=domain).exists()

    @staticmethod
    def is_taken(address: str) -> bool:
        """True if a mailbox, login or alias already uses this address."""
        local, domain = split_address(address)
        full = f'{local}@{domain}'
        return (
            Mailbox.objects.filter(local_part=local, domain__name=domain).exists()
            or MailUser.objects.filter(email=full).exists()
            or Alias.objects.filter(source=full).exists()
        )

    @staticmethod
    @transaction.atomic
    def create(
        domain_name: str,
        local_part: str,
        password: str | None = None,
        *,
        quota_bytes: int = DEFAULT_QUOTA_BYTES,
        is_admin: bool = False,
        enforce_reserved: bool = False,
        adopt_existing_login: bool = False,
    ) -> tuple[Mailbox, MailUser]:
        """Create the mailbox and its login together (all or nothing).

        ``password=None`` creates an invite-pending login with an unusable
        password (Dovecot rejects auth until the owner sets one via the
        setup link). The setup wizard and self-registration pass a real
        password; the admin console passes ``None``.

        ``adopt_existing_login`` lets the first-run wizard attach a mailbox to the
        administrator login that bootstrap created with the same address.

        ``quota_bytes`` defaults to 1024 MB; pass ``0`` for unlimited.
        """
        domain = _get_domain(domain_name)
        local = validate_local_part(local_part, reserved_blocked=enforce_reserved)
        address = f'{local}@{domain.name}'
        if len(address) > _MAX_ADDRESS:
            raise MailboxError('That address is too long.')
        if quota_bytes < 0:
            raise MailboxError('Quota cannot be negative.')
        if password is not None:
            _validate_password(password, address)
        existing_login = MailUser.objects.filter(email=address).first()
        adopt = (
            adopt_existing_login
            and existing_login is not None
            and not Mailbox.objects.filter(local_part=local, domain=domain).exists()
            and not Alias.objects.filter(source=address).exists()
        )
        if not adopt and MailboxService.is_taken(address):
            raise MailboxError(f'{address} is already in use.')
        try:
            mailbox = Mailbox.objects.create(
                domain=domain, local_part=local, quota_bytes=quota_bytes
            )
            if adopt:
                assert existing_login is not None
                user = existing_login
                if password is not None:
                    user.set_password(password)
                user.is_active = True
                user.is_staff = user.is_staff or is_admin
                user.save()
            elif password is None:
                user = MailUser.objects.create_user(
                    email=address, password=None, is_active=True, is_staff=is_admin
                )
                user.set_unusable_password()
                user.save(update_fields=['password'])
            else:
                user = MailUser.objects.create_user(
                    email=address, password=password, is_active=True, is_staff=is_admin
                )
        except IntegrityError as exc:
            raise MailboxError(f'{address} is already in use.') from exc
        return mailbox, user

    @staticmethod
    @transaction.atomic
    def claim_for_login(
        user: MailUser,
        domain_name: str,
        local_part: str,
        *,
        quota_bytes: int = DEFAULT_QUOTA_BYTES,
    ) -> Mailbox:
        """Give an already-verified login its own mailbox address (self-registration).

        The login is renamed to the new address, which is what Dovecot and Postfix
        use to find the mailbox, and the password the person chose is kept.
        """
        domain = _get_domain(domain_name)
        local = validate_local_part(local_part, reserved_blocked=True)
        address = f'{local}@{domain.name}'
        if len(address) > _MAX_ADDRESS:
            raise MailboxError('That address is too long.')
        if MailboxService.is_taken(address):
            raise MailboxError(f'{address} is already taken. Try another name.')
        try:
            mailbox = Mailbox.objects.create(
                domain=domain, local_part=local, quota_bytes=quota_bytes
            )
            user.email = address
            user.save(update_fields=['email'])
        except IntegrityError as exc:
            raise MailboxError(f'{address} is already taken. Try another name.') from exc
        return mailbox

    @staticmethod
    def get_user(address: str) -> MailUser:
        user = MailUser.objects.filter(email=address.strip().lower()).first()
        if user is None:
            raise MailboxError(f'No login exists for {address}.')
        return user

    @staticmethod
    @transaction.atomic
    def set_password(address: str, password: str) -> None:
        user = MailboxService.get_user(address)
        _validate_password(password, user.email)
        user.set_password(password)
        user.save()

    @staticmethod
    @transaction.atomic
    def set_quota(address: str, quota_bytes: int) -> None:
        if quota_bytes < 0:
            raise MailboxError('Quota cannot be negative.')
        local, domain = split_address(address)
        updated = Mailbox.objects.filter(local_part=local, domain__name=domain).update(
            quota_bytes=quota_bytes
        )
        if not updated:
            raise MailboxError(f'{address} does not exist.')

    @staticmethod
    def _ensure_not_last_admin(user: MailUser) -> None:
        if user.is_active and (user.is_staff or user.is_superuser):
            others = MailUser.objects.filter(is_active=True).exclude(pk=user.pk)
            if not (others.filter(is_staff=True) | others.filter(is_superuser=True)).exists():
                raise MailboxError(
                    'This is the last administrator and cannot be disabled or removed.'
                )

    @staticmethod
    @transaction.atomic
    def set_active(address: str, active: bool) -> None:
        user = MailboxService.get_user(address)
        if not active:
            MailboxService._ensure_not_last_admin(user)
        user.is_active = active
        user.save(update_fields=['is_active'])

    @staticmethod
    @transaction.atomic
    def set_admin(address: str, is_admin: bool) -> None:
        """Grant or revoke console-admin rights (never removes the last admin)."""
        user = MailboxService.get_user(address)
        if user.is_staff == is_admin:
            return
        if not is_admin and not user.is_superuser:
            MailboxService._ensure_not_last_admin(user)
        user.is_staff = is_admin
        user.save(update_fields=['is_staff'])

    @staticmethod
    @transaction.atomic
    def delete(address: str) -> None:
        """Remove the mailbox row, its login and aliases that originate from it.

        The mail on disk is left in place: the console mounts the mail volume
        read-only, so deleting data stays a deliberate operator action.
        """
        local, domain = split_address(address)
        full = f'{local}@{domain}'
        mailbox = Mailbox.objects.filter(local_part=local, domain__name=domain).first()
        if mailbox is None:
            raise MailboxError(f'{full} does not exist.')
        user = MailUser.objects.filter(email=full).first()
        if user is not None:
            MailboxService._ensure_not_last_admin(user)
            user.delete()
        Alias.objects.filter(source=full).delete()
        mailbox.delete()

    @staticmethod
    def list_rows() -> list[MailboxRow]:
        mailboxes = list(
            Mailbox.objects.select_related('domain').order_by('domain__name', 'local_part')
        )
        users = {
            u.email: u
            for u in MailUser.objects.filter(
                email__in=[f'{m.local_part}@{m.domain.name}' for m in mailboxes]
            )
        }
        rows = []
        for m in mailboxes:
            address = f'{m.local_part}@{m.domain.name}'
            user = users.get(address)
            rows.append(
                MailboxRow(
                    id=str(m.id),
                    address=address,
                    domain=m.domain.name,
                    quota_bytes=m.quota_bytes,
                    is_active=bool(user and user.is_active),
                    is_admin=bool(user and (user.is_staff or user.is_superuser)),
                    created_at=m.created_at.date().isoformat() if m.created_at else '',
                    invite_pending=bool(user is None or not user.has_usable_password()),
                )
            )
        return rows


class MailboxInviteService:
    """Single-use setup links so admins never handle plaintext passwords."""

    _generator = PasswordResetTokenGenerator()

    @staticmethod
    def make_token(address: str) -> tuple[str, str]:
        """Return ``(uidb64, token)`` for ``address``; raises MailboxError if unknown."""
        user = MailboxService.get_user(address)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        return uid, MailboxInviteService._generator.make_token(user)

    @staticmethod
    def check_token(uidb64: str, token: str) -> MailUser | None:
        """Return the user if ``(uidb64, token)`` is valid, else None (no DB write)."""
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = MailUser.objects.filter(pk=uid).first()
        except (ValueError, TypeError):
            return None
        if user is None:
            return None
        if MailboxInviteService._generator.check_token(user, token):
            return user
        return None

    @staticmethod
    @transaction.atomic
    def accept(uidb64: str, token: str, password: str) -> MailUser:
        """Validate the link and set the owner's password (single-use)."""
        user = MailboxInviteService.check_token(uidb64, token)
        if user is None:
            raise MailboxError('This setup link is invalid or has expired.')
        _validate_password(password, user.email)
        user.set_password(password)
        user.is_active = True
        user.save()
        return user


class AliasService:
    @staticmethod
    def list_rows() -> list[AliasRow]:
        return [
            AliasRow(str(a.id), a.source, a.destination, a.domain.name)
            for a in Alias.objects.select_related('domain').order_by('domain__name', 'source')
        ]

    @staticmethod
    @transaction.atomic
    def create(source: str, destination: str) -> Alias:
        local, domain_name = split_address(source)
        validate_local_part(local)
        domain = _get_domain(domain_name)
        full_source = f'{local}@{domain.name}'
        destination = destination.strip().lower()
        try:
            validate_email(destination)
        except ValidationError as exc:
            raise MailboxError('Enter a valid destination email address.') from exc
        if len(full_source) > _MAX_ADDRESS:
            raise MailboxError('That alias is too long.')
        if destination == full_source:
            raise MailboxError('An alias cannot forward to itself.')
        if Mailbox.objects.filter(local_part=local, domain=domain).exists():
            raise MailboxError(
                f'{full_source} is a mailbox. Remove the mailbox or choose another alias name.'
            )
        # A -> B while B -> A would bounce mail around forever.
        if Alias.objects.filter(source=destination, destination=full_source).exists():
            raise MailboxError('That would create a forwarding loop.')
        try:
            alias, _ = Alias.objects.get_or_create(
                domain=domain, source=full_source, destination=destination
            )
        except IntegrityError as exc:
            raise MailboxError('That alias already exists.') from exc
        return alias

    @staticmethod
    def delete(alias_id: str) -> None:
        deleted, _ = Alias.objects.filter(id=alias_id).delete()
        if not deleted:
            raise MailboxError('That alias no longer exists.')
