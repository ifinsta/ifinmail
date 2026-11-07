"""mail — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers never touch the database; viewsets feed them service results.
Passwords are write-only inputs and never serialized back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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


class CampaignRecipientIn(Schema):
    """One person a campaign goes to, with the values for the message's ``{{merge}}`` tags."""

    email: str
    merge: dict[str, str | int | float | None] = Field(default_factory=dict)


class CampaignIn(Schema):
    """``POST /campaigns``: one message, many recipients, one email each (Marketing plugin).

    The subject, text and html may hold ``{{name}}`` tags (``{{name|fallback}}`` for a person
    with no value). ``{{email}}`` and ``{{unsubscribe_url}}`` are always available. The footer with
    your postal address and the unsubscribe link is added to every email.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias='from', description="The sender; one of the key's allowed senders.")
    name: str = Field(default='', max_length=120, description='Your own label for the campaign.')
    subject: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Required unless a template gives it. What you give wins over the template's.",
    )
    text: str | None = Field(default=None, max_length=1_000_000)
    html: str | None = Field(default=None, max_length=1_000_000)
    template: str | None = Field(
        default=None,
        description='Start from this template (its id): the subject and bodies you leave out '
        'come from it. It is copied when the campaign is created.',
    )
    reply_to: str | None = None
    track_opens: bool | None = Field(
        default=None,
        description='Count opens with a tracking pixel in the html. Left out: the server default.',
    )
    track_clicks: bool | None = Field(
        default=None,
        description='Send the html links through the server to count clicks. Left out: the '
        'server default.',
    )
    send_at: datetime | None = Field(
        default=None,
        description='Start sending then, with a time zone (2026-03-01T09:00:00+01:00, or ...Z). '
        'Left out, it starts now. From a minute to a year ahead.',
    )
    recipients: list[CampaignRecipientIn] = Field(default_factory=list, max_length=100_000)
    audience: str | None = Field(
        default=None,
        description='Send to everyone on this audience (its id) instead of listing recipients. '
        'The list is copied when the campaign is created.',
    )


class CampaignCreatedV1(Schema):
    """The campaign exists and is being sent at the server's pace; nothing is sent in this call."""

    id: str
    status: str  # sending, or scheduled when send_at was given
    queued: int  # recipients that will be sent to
    skipped: dict[str, int]  # reason -> how many were left out (suppressed, opted_out, ...)


class CampaignV1(Schema):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    status: str  # scheduled | sending | paused | completed | cancelled
    status_detail: str  # why it is paused
    from_: str = Field(alias='from')
    subject: str
    audience: str | None  # the audience it was sent to, if any
    template: str | None  # the template it started from, if any
    send_at: str | None  # when a scheduled campaign starts
    track_opens: bool
    track_clicks: bool
    created_at: str
    finished_at: str | None
    # Recipients by status: pending, sending, sent, failed, skipped.
    recipients: dict[str, int]
    bounce_rate: float | None  # percent of what was sent that bounced, so far

    @classmethod
    def of(cls, row, counts: dict[str, int], bounce_rate: float | None) -> CampaignV1:  # noqa: ANN001
        return cls(
            id=str(row.pk),
            name=row.name,
            status=row.status,
            status_detail=row.status_detail,
            from_=row.sender,
            subject=row.subject,
            audience=str(row.audience_id) if row.audience_id else None,
            template=str(row.template_id) if row.template_id else None,
            send_at=row.send_at.isoformat(timespec='seconds') if row.send_at else None,
            track_opens=row.track_opens,
            track_clicks=row.track_clicks,
            created_at=row.created_at.isoformat(timespec='seconds'),
            finished_at=row.finished_at.isoformat(timespec='seconds') if row.finished_at else None,
            recipients=counts,
            bounce_rate=bounce_rate,
        )


class CampaignRecipientV1(Schema):
    email: str
    status: str  # pending | sending | sent | failed | skipped
    detail: str  # why it was skipped or failed
    message_id: str
    sent_at: str | None
    opens: int  # times the email was opened (see the notes on tracking)
    first_opened_at: str | None
    clicks: int
    first_clicked_at: str | None

    @classmethod
    def of(cls, row) -> CampaignRecipientV1:  # noqa: ANN001
        return cls(
            email=row.address,
            status=row.status,
            detail=row.detail,
            message_id=row.message_id,
            sent_at=row.sent_at.isoformat(timespec='seconds') if row.sent_at else None,
            opens=row.opens,
            first_opened_at=_when(row.first_opened_at),
            clicks=row.clicks,
            first_clicked_at=_when(row.first_clicked_at),
        )


def _when(value: datetime | None) -> str | None:
    return value.isoformat(timespec='seconds') if value else None


class CampaignReportCountV1(Schema):
    people: int  # distinct people
    total: int  # every time
    rate: float | None  # percent of the emails sent


class CampaignClickReportV1(CampaignReportCountV1):
    of_openers: float | None  # percent of the people who opened that also clicked


class CampaignLinkReportV1(Schema):
    url: str  # as written in the message, merge tags and all
    clicks: int
    people: int


class CampaignTimelineV1(Schema):
    at: str  # the start of the hour (or day); people counted at their first open or click
    opens: int
    clicks: int


class CampaignTrackingV1(Schema):
    opens: bool
    clicks: bool


class CampaignReportV1(Schema):
    """How a campaign did. Read the notes under ``GET /campaigns/{id}/report`` before comparing."""

    id: str
    status: str
    sent: int
    failed: int
    skipped: int
    bounced: int | None  # None when the count is not available
    tracking: CampaignTrackingV1
    opens: CampaignReportCountV1
    clicks: CampaignClickReportV1
    links: list[CampaignLinkReportV1]
    timeline: list[CampaignTimelineV1]


class CampaignScheduleV1(Schema):
    send_at: datetime = Field(description='With a time zone; from a minute to a year ahead.')


class TemplateCreateV1(Schema):
    name: str = Field(min_length=1, max_length=120, description='Your own label for it.')
    subject: str = Field(min_length=1, max_length=255)
    text: str | None = Field(default=None, max_length=1_000_000)
    html: str | None = Field(default=None, max_length=1_000_000)


class TemplateChangeV1(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, max_length=1_000_000)
    html: str | None = Field(default=None, max_length=1_000_000)


class TemplateTagV1(Schema):
    name: str
    required: bool  # some use has no fallback: a person without a value is skipped


class TemplateV1(Schema):
    id: str
    name: str
    subject: str
    text: str
    html: str
    tags: list[TemplateTagV1]  # the merge tags it uses
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, row, tags: list[dict]) -> TemplateV1:  # noqa: ANN001
        return cls(
            id=str(row.pk),
            name=row.name,
            subject=row.subject,
            text=row.text,
            html=row.html,
            tags=[TemplateTagV1(**tag) for tag in tags],
            created_at=row.created_at.isoformat(timespec='seconds'),
            updated_at=row.updated_at.isoformat(timespec='seconds'),
        )


class TemplatePreviewIn(Schema):
    merge: dict[str, str | int | float | None] = Field(default_factory=dict)
    email: str = Field(default='', description='Fills {{email}}; a made-up address if left out.')


class TemplatePreviewV1(Schema):
    subject: str
    text: str
    html: str
    missing: list[str]  # tags with no value and no fallback: a campaign would skip that person


class AudienceCreateV1(Schema):
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(description='The sending domain this list is for; one the key sends from.')
    description: str = Field(default='', max_length=300)


class AudienceChangeV1(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)


class AudienceV1(Schema):
    id: str
    name: str
    description: str
    domain: str
    created_at: str
    # How many contacts, and how many of them a campaign would actually reach.
    contacts: dict[str, int]  # total | reachable | opted_out | suppressed

    @classmethod
    def of(cls, row, counts: dict[str, int]) -> AudienceV1:  # noqa: ANN001
        return cls(
            id=str(row.pk),
            name=row.name,
            description=row.description,
            domain=row.domain,
            created_at=row.created_at.isoformat(timespec='seconds'),
            contacts=counts,
        )


class AudienceContactIn(Schema):
    """One person to add to an audience, or to update if the address is already there."""

    email: str
    merge: dict[str, str | int | float | None] | None = Field(
        default=None,
        description='Values for the message tags. Left out, an existing contact keeps its values.',
    )
    source: str = Field(default='', max_length=40, description='Where this person came from.')


class AudienceContactsIn(Schema):
    contacts: list[AudienceContactIn] = Field(min_length=1, max_length=1000)


class AudienceImportV1(Schema):
    added: int
    updated: int  # already there, with different values
    unchanged: int  # already there, nothing to change
    invalid: int  # not an address, or values that cannot be used
    duplicate: int  # named twice in this request


class AudienceContactV1(Schema):
    email: str
    merge: dict[str, str]
    source: str
    status: str  # reachable | opted_out | suppressed
    created_at: str

    @classmethod
    def of(cls, row, status: str) -> AudienceContactV1:  # noqa: ANN001
        return cls(
            email=row.address,
            merge=row.merge,
            source=row.source,
            status=status,
            created_at=row.created_at.isoformat(timespec='seconds'),
        )


class MarketingOptOutV1(Schema):
    domain: str  # our sending domain
    address: str
    source: str  # one-click | api | manual
    created_at: str

    @classmethod
    def of(cls, row) -> MarketingOptOutV1:  # noqa: ANN001
        return cls(
            domain=row.domain,
            address=row.address,
            source=row.source,
            created_at=row.created_at.isoformat(timespec='seconds'),
        )


class MarketingOptOutCreateV1(Schema):
    address: str
    domain: str  # one of the domains the key may send from


__all__ = [
    'CampaignClickReportV1',
    'CampaignLinkReportV1',
    'CampaignReportCountV1',
    'CampaignReportV1',
    'CampaignTimelineV1',
    'CampaignTrackingV1',
    'CampaignScheduleV1',
    'TemplateChangeV1',
    'TemplateCreateV1',
    'TemplatePreviewIn',
    'TemplatePreviewV1',
    'TemplateTagV1',
    'TemplateV1',
    'AudienceChangeV1',
    'AudienceContactIn',
    'AudienceContactV1',
    'AudienceContactsIn',
    'AudienceCreateV1',
    'AudienceImportV1',
    'AudienceV1',
    'CampaignCreatedV1',
    'CampaignIn',
    'CampaignRecipientIn',
    'CampaignRecipientV1',
    'CampaignV1',
    'MarketingOptOutCreateV1',
    'MarketingOptOutV1',
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
