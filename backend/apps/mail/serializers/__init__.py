"""mail — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers never touch the database; viewsets feed them service results.
Passwords are write-only inputs and never serialized back.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninja import Schema
from pydantic import ConfigDict, Field

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


class MessageIn(Schema):
    """``POST /messages``. Addresses are bare (``name@domain``); there are no attachments yet."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias='from', description="The sender; one of the key's allowed senders.")
    to: list[str] = Field(min_length=1, max_length=100)
    cc: list[str] = Field(default_factory=list, max_length=100)
    bcc: list[str] = Field(default_factory=list, max_length=100)
    reply_to: str | None = None
    subject: str = Field(min_length=1, max_length=255)
    text: str | None = Field(default=None, max_length=1_000_000)
    html: str | None = Field(default=None, max_length=1_000_000)


class MessageAcceptedV1(Schema):
    """The server accepted the message for delivery (it is not a delivery receipt)."""

    id: str  # the Message-ID header, without the angle brackets
    status: str  # "queued", or "captured" for a sandbox key (kept, not delivered)
    recipients: int


class WebhookCreateV1(Schema):
    name: str
    url: str
    events: list[str]
    mailboxes: list[str] = []  # message.received only


class WebhookV1(Schema):
    id: str
    name: str
    url: str
    events: list[str]
    mailboxes: list[str]
    active: bool
    failing_since: str | None
    last_success_at: str | None
    last_error: str
    created_at: str

    @classmethod
    def of(cls, row) -> WebhookV1:  # noqa: ANN001
        def stamp(value) -> str | None:  # noqa: ANN001
            return value.isoformat(timespec='seconds') if value else None

        return cls(
            id=str(row.pk),
            name=row.name,
            url=row.url,
            events=list(row.events),
            mailboxes=list(row.mailboxes),
            active=row.active,
            failing_since=stamp(row.failing_since),
            last_success_at=stamp(row.last_success_at),
            last_error=row.last_error,
            created_at=stamp(row.created_at) or '',
        )


class WebhookCreatedV1(WebhookV1):
    """Returned once, at creation: the signing secret is not shown again."""

    secret: str


class WebhookDeliveryV1(Schema):
    id: str
    event_id: str
    event_type: str
    status: str  # pending | delivered | failed
    attempts: int
    last_status_code: int | None
    last_error: str
    created_at: str
    next_attempt_at: str | None

    @classmethod
    def of(cls, row) -> WebhookDeliveryV1:  # noqa: ANN001
        return cls(
            id=str(row.pk),
            event_id=row.event_id,
            event_type=row.event_type,
            status=row.status,
            attempts=row.attempts,
            last_status_code=row.last_status_code,
            last_error=row.last_error,
            created_at=row.created_at.isoformat(timespec='seconds'),
            next_attempt_at=row.next_attempt_at.isoformat(timespec='seconds')
            if row.next_attempt_at
            else None,
        )


class SandboxMessageV1(Schema):
    """A message a sandbox key sent, kept for inspection and never delivered."""

    id: str
    message_id: str
    sender: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    reply_to: str
    subject: str
    text: str
    html: str
    created_at: str

    @classmethod
    def of(cls, row) -> SandboxMessageV1:  # noqa: ANN001
        return cls(
            id=str(row.pk),
            message_id=row.message_id,
            sender=row.sender,
            to=list(row.to),
            cc=list(row.cc),
            bcc=list(row.bcc),
            reply_to=row.reply_to,
            subject=row.subject,
            text=row.text,
            html=row.html,
            created_at=row.created_at.isoformat(timespec='seconds'),
        )


__all__ = [
    'WebhookCreateV1',
    'WebhookCreatedV1',
    'WebhookDeliveryV1',
    'WebhookV1',
    'SandboxMessageV1',
    'AliasCreateIn',
    'AliasCreateV1',
    'AliasOut',
    'AliasV1',
    'MailboxCreateIn',
    'MailboxCreateV1',
    'MailboxOut',
    'MailboxUpdateV1',
    'MailboxV1',
    'MessageAcceptedV1',
    'MessageIn',
    'OutboundStateOut',
]
