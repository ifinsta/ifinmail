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
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from backend.apps.accounts.models import MailUser
from backend.apps.domains.models import Domain

from ..models import Alias, Mailbox
from ..types.provisioning import AliasRow, MailboxError, MailboxRow
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
        password: str,
        *,
        quota_bytes: int = 0,
        is_admin: bool = False,
        enforce_reserved: bool = False,
        adopt_existing_login: bool = False,
    ) -> tuple[Mailbox, MailUser]:
        """Create the mailbox and its login together (all or nothing).

        ``adopt_existing_login`` lets the first-run wizard attach a mailbox to the
        administrator login that bootstrap created with the same address.
        """
        domain = _get_domain(domain_name)
        local = validate_local_part(local_part, reserved_blocked=enforce_reserved)
        address = f'{local}@{domain.name}'
        if len(address) > _MAX_ADDRESS:
            raise MailboxError('That address is too long.')
        if quota_bytes < 0:
            raise MailboxError('Quota cannot be negative.')
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
                user = existing_login
                user.set_password(password)
                user.is_active = True
                user.is_staff = user.is_staff or is_admin
                user.save()
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
        user: MailUser, domain_name: str, local_part: str, *, quota_bytes: int = 0
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
                )
            )
        return rows


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
