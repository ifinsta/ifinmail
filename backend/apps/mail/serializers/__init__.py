"""mail — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers never touch the database; viewsets feed them service results.
Passwords are write-only inputs and never serialized back.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninja import Schema

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


# -- v1 API contract ------------------------------------------------------------------------
# Wire shapes of /api/v1. They are written out here (not derived from the dataclasses above) so
# that refactoring the internals can never change what an integration receives. Within v1 fields
# are only ever added; a removal or a changed meaning is a new version.


class MailboxV1(Schema):
    address: str
    domain: str
    quota_bytes: int
    is_active: bool
    console_access: bool
    invite_pending: bool
    created_at: str

    @classmethod
    def of(cls, out: MailboxOut) -> MailboxV1:
        return cls(
            address=out.address,
            domain=out.domain,
            quota_bytes=out.quota_bytes,
            is_active=out.is_active,
            console_access=out.is_admin,
            invite_pending=out.invite_pending,
            created_at=out.created_at,
        )


class MailboxCreateV1(Schema):
    address: str
    password: str | None = None
    quota_bytes: int | None = None


class MailboxUpdateV1(Schema):
    quota_bytes: int | None = None
    is_active: bool | None = None
    password: str | None = None


class AliasV1(Schema):
    id: str
    source: str
    destination: str
    domain: str

    @classmethod
    def of(cls, out: AliasOut) -> AliasV1:
        return cls(id=out.id, source=out.source, destination=out.destination, domain=out.domain)


class AliasCreateV1(Schema):
    source: str
    destination: str


__all__ = [
    'AliasCreateIn',
    'AliasCreateV1',
    'AliasOut',
    'AliasV1',
    'MailboxCreateIn',
    'MailboxCreateV1',
    'MailboxOut',
    'MailboxUpdateV1',
    'MailboxV1',
    'OutboundStateOut',
]
