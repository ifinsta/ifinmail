"""Typed values for mailbox and alias management."""

from __future__ import annotations

from dataclasses import dataclass


class MailboxError(ValueError):
    """A mailbox or alias request that cannot be fulfilled (message is user-safe)."""


@dataclass(frozen=True)
class MailboxRow:
    id: str
    address: str
    domain: str
    quota_bytes: int
    is_active: bool
    is_admin: bool
    created_at: str


@dataclass(frozen=True)
class AliasRow:
    id: str
    source: str
    destination: str
    domain: str
