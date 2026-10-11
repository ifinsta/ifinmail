"""Typed values for mailbox and alias management."""

from .provisioning import AliasRow, MailboxError, MailboxRow
from .quota import DEFAULT_QUOTA_BYTES, DEFAULT_QUOTA_MB, MB, QuotaBudget, human_bytes
from .reserved import RESERVED_LOCAL_PARTS

__all__ = [
    'DEFAULT_QUOTA_BYTES',
    'DEFAULT_QUOTA_MB',
    'MB',
    'RESERVED_LOCAL_PARTS',
    'AliasRow',
    'MailboxError',
    'MailboxRow',
    'QuotaBudget',
    'human_bytes',
]
