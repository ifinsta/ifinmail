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
    # Bulk or marketing mail: with the Sender compliance plugin it gets one-click unsubscribe
    # headers (RFC 8058) and must go to one recipient per message.
    unsubscribe: bool = False


class MessageAcceptedV1(Schema):
    """The server accepted the message for delivery (it is not a delivery receipt)."""

    id: str  # the Message-ID header, without the angle brackets
    # "queued"; "captured" for a sandbox key (kept, not delivered); "pending_approval" when the
    # Human approval plugin holds it (``id`` is then the approval's id: GET /approvals/{id}).
    status: str
    recipients: int
    suppressed: list[str] = []  # left out: on the suppression list (Sender compliance)


class InboxCreateV1(Schema):
    name: str = ''  # the part before @; random ("agent-1a2b3c4d") when empty
    label: str = ''  # your own note, e.g. the task it is for
    ttl_hours: int | None = None  # 0: kept until deleted; empty: the plugin's default


class InboxV1(Schema):
    address: str
    label: str
    created_at: str
    expires_at: str | None

    @classmethod
    def of(cls, row) -> InboxV1:  # noqa: ANN001
        return cls(
            address=row.address,
            label=row.label,
            created_at=row.created_at.isoformat(timespec='seconds'),
            expires_at=row.expires_at.isoformat(timespec='seconds') if row.expires_at else None,
        )


class InboxMessageV1(Schema):
    """One received message, without its body."""

    model_config = ConfigDict(populate_by_name=True)

    uid: int
    message_id: str
    from_: str = Field(alias='from')
    to: list[str]
    subject: str
    date: str
    size: int
    seen: bool


class InboxAttachmentV1(Schema):
    filename: str
    content_type: str
    size: int


class RiskV1(Schema):
    """Injection shield verdict: how likely the message carries instructions planted for an
    agent, and why. ``hidden_text`` is what a person reading the message would not see."""

    score: int
    level: str  # none | low | medium | high
    reasons: list[str]
    hidden_text: str


class InboxMessageFullV1(InboxMessageV1):
    cc: list[str]
    reply_to: str
    delivered_to: list[str]
    text: str
    html: str  # as sent; never render it without sanitising
    headers: dict[str, str]
    attachments: list[InboxAttachmentV1]
    risk: RiskV1 | None = None  # with the Injection shield plugin
    safe_text: str | None = None  # what a person would see: read this, not ``text``
    held: bool = False


class FoundCodeV1(Schema):
    value: str
    shown: str
    score: int
    where: str


class FoundLinkV1(Schema):
    url: str
    text: str
    score: int


class InboxCodeV1(Schema):
    """What a verification email asks for: the best guess first, then the alternatives."""

    model_config = ConfigDict(populate_by_name=True)

    uid: int
    subject: str
    from_: str = Field(alias='from')
    code: str | None
    link: str | None
    risk: RiskV1 | None = None
    codes: list[FoundCodeV1]
    links: list[FoundLinkV1]


class InboxWaitV1(InboxCodeV1):
    message: InboxMessageV1


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


class ApprovalV1(Schema):
    """A message held for a person's approval, and what became of it."""

    id: str
    status: str  # pending | sent | rejected | expired | failed
    sender: str
    to: list[str]
    cc: list[str]
    subject: str
    reason: str
    created_at: str
    decided_at: str | None
    decided_by: str
    note: str
    message_id: str  # the sent message's id (for delivery events), once sent

    @classmethod
    def of(cls, row) -> ApprovalV1:  # noqa: ANN001
        return cls(
            id=str(row.pk),
            status=row.status,
            sender=row.sender,
            to=list(row.to),
            cc=list(row.cc),
            subject=row.subject,
            reason=row.reason,
            created_at=row.created_at.isoformat(timespec='seconds'),
            decided_at=row.decided_at.isoformat(timespec='seconds') if row.decided_at else None,
            decided_by=row.decided_by,
            note=row.note,
            message_id=row.message_id,
        )


class ApprovalDecisionV1(Schema):
    note: str = ''


class SuppressionV1(Schema):
    domain: str  # our sending domain
    address: str
    reason: str  # bounced | unsubscribed | manual
    detail: str
    created_at: str

    @classmethod
    def of(cls, row) -> SuppressionV1:  # noqa: ANN001
        return cls(
            domain=row.domain,
            address=row.address,
            reason=row.reason,
            detail=row.detail,
            created_at=row.created_at.isoformat(timespec='seconds'),
        )


class SuppressionCreateV1(Schema):
    address: str
    domain: str  # one of the domains the key may send from
    detail: str = ''


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
    'SuppressionCreateV1',
    'SuppressionV1',
    'ApprovalDecisionV1',
    'ApprovalV1',
    'RiskV1',
    'FoundCodeV1',
    'FoundLinkV1',
    'InboxAttachmentV1',
    'InboxCodeV1',
    'InboxCreateV1',
    'InboxMessageFullV1',
    'InboxMessageV1',
    'InboxV1',
    'InboxWaitV1',
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
