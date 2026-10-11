"""Mailbox viewset — operations over MailboxService.

Service errors (MailboxError, message is user-safe) propagate to the caller;
the API layer maps them to status codes.
"""

from __future__ import annotations

from backend.apps.mail.serializers import MailboxCreateIn, MailboxOut
from backend.apps.mail.services.mailboxes import MailboxService


def list_mailboxes() -> list[MailboxOut]:
    """Every mailbox with status and role. No passwords, no hashes."""
    return [MailboxOut.from_row(row) for row in MailboxService.list_rows()]


def create_mailbox(payload: MailboxCreateIn) -> MailboxOut:
    """Create mailbox + login together; returns the shaped row."""
    MailboxService.create(
        payload.domain_name,
        payload.local_part,
        payload.password,
        quota_bytes=payload.quota_bytes,
        is_admin=payload.is_admin,
    )
    address = f'{payload.local_part.strip().lower()}@{payload.domain_name.strip().lower()}'
    rows = [r for r in MailboxService.list_rows() if r.address == address]
    return MailboxOut.from_row(rows[0])


def set_password(address: str, password: str) -> None:
    MailboxService.set_password(address, password)


def set_quota(address: str, quota_bytes: int) -> None:
    MailboxService.set_quota(address, quota_bytes)


def set_active(address: str, active: bool) -> None:
    MailboxService.set_active(address, active)


def set_admin(address: str, is_admin: bool) -> None:
    MailboxService.set_admin(address, is_admin)


def delete_mailbox(address: str) -> None:
    MailboxService.delete(address)


__all__ = [
    'create_mailbox',
    'delete_mailbox',
    'list_mailboxes',
    'set_active',
    'set_admin',
    'set_password',
    'set_quota',
]
