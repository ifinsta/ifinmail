"""mail — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers never touch the database; viewsets feed them service results.
Passwords are write-only inputs and never serialized back.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.apps.mail.services.postfix_runtime import OutboundState
from backend.apps.mail.types.provisioning import AliasRow, MailboxRow
from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES


@dataclass(frozen=True)
class MailboxCreateIn:
    domain_name: str
    local_part: str
    password: str | None = None
    quota_bytes: int = DEFAULT_QUOTA_BYTES
    is_admin: bool = False


@dataclass(frozen=True)
class MailboxOut:
    id: str
    address: str
    domain: str
    quota_bytes: int
    is_active: bool
    is_admin: bool
    created_at: str
    invite_pending: bool = False

    @classmethod
    def from_row(cls, row: MailboxRow) -> MailboxOut:
        return cls(
            id=row.id,
            address=row.address,
            domain=row.domain,
            quota_bytes=row.quota_bytes,
            is_active=row.is_active,
            is_admin=row.is_admin,
            created_at=row.created_at,
            invite_pending=row.invite_pending,
        )


@dataclass(frozen=True)
class AliasCreateIn:
    source: str
    destination: str


@dataclass(frozen=True)
class AliasOut:
    id: str
    source: str
    destination: str
    domain: str

    @classmethod
    def from_row(cls, row: AliasRow) -> AliasOut:
        return cls(id=row.id, source=row.source, destination=row.destination, domain=row.domain)


@dataclass(frozen=True)
class OutboundStateOut:
    smart_host_enabled: bool
    smart_host: str
    smtp_proxy_enabled: bool
    smtp_proxy: str
    max_hops: int

    @classmethod
    def from_state(cls, state: OutboundState) -> OutboundStateOut:
        return cls(
            smart_host_enabled=state.smart_host_enabled,
            smart_host=state.smart_host,
            smtp_proxy_enabled=state.smtp_proxy_enabled,
            smtp_proxy=state.smtp_proxy,
            max_hops=state.max_hops,
        )


__all__ = [
    'AliasCreateIn',
    'AliasOut',
    'MailboxCreateIn',
    'MailboxOut',
    'OutboundStateOut',
]
