"""mail — api.py: the mail routes of the v1 API (urls.py → api.py → viewsets/ contract).

Mailboxes and aliases for integrations. Scope: ``mail.manage``. Mailboxes whose login has console
access are read-only here (see ``viewsets.mailboxes.ensure_plain``); the plain re-exports below
stay for in-process callers and tests.
"""

from typing import Annotated

from django.core.cache import cache
from django.http import HttpResponse
from ninja import Header, Router, Status
from ninja.errors import HttpError
from ninja.pagination import LimitOffsetPagination, paginate

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.photos import Crop, PhotoError, PhotoService
from backend.apps.accounts.services.tokens import key_id
from backend.apps.accounts.viewsets.auth import ApiRequest, actor, require_scope
from backend.apps.accounts.viewsets.errors import errors, problem
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.mail.serializers import (
    InboxCodeV1,
    InboxCreateV1,
    InboxMessageFullV1,
    InboxMessageV1,
    InboxV1,
    InboxWaitV1,
    WebhookCreatedV1,
    WebhookCreateV1,
    WebhookDeliveryV1,
    WebhookV1,
    SandboxMessageV1,
    AliasCreateIn,
    AliasCreateV1,
    AliasV1,
    MailboxCreateIn,
    MailboxCreateV1,
    MailboxUpdateV1,
    MailboxV1,
    MessageAcceptedV1,
    MessageIn,
)
from backend.apps.mail.services.mailboxes import split_address
from backend.apps.mail.services.messages import (
    MessageService,
    SendingKey,
    SendRefused,
    SendRequest,
    digest,
)
from backend.apps.mail.types.provisioning import MailboxError
from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES

from . import viewsets as ops
from .viewsets import (
    create_alias,
    create_mailbox,
    delete_alias,
    delete_mailbox,
    get_outbound_state,
    list_aliases,
    list_mailboxes,
    render_outbound,
    set_active,
    set_admin,
    set_max_hops,
    set_password,
    set_quota,
    set_smart_host,
    set_smtp_proxy,
)

import logging

logger = logging.getLogger('backend')
router = Router(tags=['mailboxes', 'aliases', 'messages', 'sandbox', 'webhooks', 'inboxes'])
IDEMPOTENCY_TTL = 24 * 3600


def _address(raw: str) -> str:
    return raw.strip().lower()


@router.get('/mailboxes', response={200: list[MailboxV1], **errors()}, summary='List mailboxes')
@paginate(LimitOffsetPagination)
@require_scope('mail.manage')
def api_list_mailboxes(request: ApiRequest, domain: str | None = None) -> list[MailboxV1]:
    """Mailboxes, ordered by domain then name. Filter with ``?domain=example.com``."""
    wanted = _address(domain) if domain else None
    return [MailboxV1.of(r) for r in ops.list_mailboxes() if wanted is None or r.domain == wanted]


@router.post(
    '/mailboxes', response={201: MailboxV1, **errors(409, 422)}, summary='Create a mailbox'
)
@require_scope('mail.manage')
def api_create_mailbox(request: ApiRequest, payload: MailboxCreateV1) -> Status[MailboxV1]:
    """Create a mailbox and its login together. Without a password the login is *invited*:
    it cannot sign in until its owner sets one through the setup link."""
    try:
        local, domain = split_address(_address(payload.address))
        created = ops.create_mailbox(
            MailboxCreateIn(
                domain_name=domain,
                local_part=local,
                password=payload.password,
                quota_bytes=DEFAULT_QUOTA_BYTES
                if payload.quota_bytes is None
                else payload.quota_bytes,
                is_admin=False,  # a key never creates a login with console access
            )
        )
    except MailboxError as exc:
        raise problem(exc) from exc
    AuditService.record(action='api_mailbox_created', user=actor(request), detail=created.address)
    return Status(201, MailboxV1.of(created))


@router.get(
    '/mailboxes/{address}', response={200: MailboxV1, **errors(404)}, summary='Get a mailbox'
)
@require_scope('mail.manage')
def api_get_mailbox(request: ApiRequest, address: str) -> MailboxV1:
    row = ops.get_mailbox(_address(address))
    if row is None:
        raise problem(MailboxError(f'{_address(address)} does not exist.'))
    return MailboxV1.of(row)


@router.patch(
    '/mailboxes/{address}',
    response={200: MailboxV1, **errors(404, 422)},
    summary='Change a mailbox',
)
@require_scope('mail.manage')
def api_update_mailbox(request: ApiRequest, address: str, payload: MailboxUpdateV1) -> MailboxV1:
    """Change the quota, disable or enable it, or set a new password. Send only what changes."""
    target = _address(address)
    changed = payload.model_dump(exclude_unset=True)
    try:
        ops.ensure_plain(target)
        if changed.get('quota_bytes') is not None:
            ops.set_quota(target, changed['quota_bytes'])
        if changed.get('is_active') is not None:
            ops.set_active(target, changed['is_active'])
        if changed.get('password'):
            ops.set_password(target, changed['password'])
        row = ops.get_mailbox(target)
    except MailboxError as exc:
        raise problem(exc) from exc
    fields = ','.join(sorted(k for k, v in changed.items() if v is not None))
    AuditService.record(
        action='api_mailbox_updated', user=actor(request), detail=f'{target} {fields}'
    )
    if row is None:  # removed between the change and the read
        raise problem(MailboxError(f'{target} does not exist.'))
    return MailboxV1.of(row)


@router.delete(
    '/mailboxes/{address}', response={204: None, **errors(404)}, summary='Delete a mailbox'
)
@require_scope('mail.manage')
def api_delete_mailbox(request: ApiRequest, address: str) -> Status[None]:
    """Remove the mailbox, its login and the aliases that start at it. Stored mail stays on disk
    until the server's operator removes it."""
    target = _address(address)
    try:
        ops.ensure_plain(target)
        ops.delete_mailbox(target)
    except MailboxError as exc:
        raise problem(exc) from exc
    AuditService.record(action='api_mailbox_deleted', user=actor(request), detail=target)
    return Status(204, None)


def _login(address: str) -> MailUser:
    user: MailUser | None = MailUser.objects.filter(email=address).first()
    if user is None:
        raise problem(MailboxError(f'{address} does not exist.'))
    return user


@router.get(
    '/mailboxes/{address}/photo',
    response={200: bytes, **errors(404)},
    summary="Get a mailbox's profile photo",
)
@require_scope('mail.manage')
def api_get_mailbox_photo(request: ApiRequest, address: str) -> HttpResponse:
    """The photo as a 256 x 256 JPEG; 404 when the mailbox has none."""
    found = PhotoService.get(_login(_address(address)).pk, 'large')
    if found is None:
        raise HttpError(404, 'This mailbox has no photo.')
    response = HttpResponse(found[0], content_type='image/jpeg')
    response['ETag'] = f'"{found[1][:32]}"'
    response['Cache-Control'] = 'private, no-store'
    return response


_PHOTO_BODY = {
    'requestBody': {
        'required': True,
        'content': {
            'multipart/form-data': {
                'schema': {
                    'type': 'object',
                    'required': ['photo'],
                    'properties': {
                        'photo': {'type': 'string', 'format': 'binary'},
                        'crop_x': {'type': 'number', 'minimum': 0, 'maximum': 1},
                        'crop_y': {'type': 'number', 'minimum': 0, 'maximum': 1},
                        'crop_size': {'type': 'number', 'minimum': 0.05, 'maximum': 1},
                    },
                }
            }
        },
    }
}


@router.post(
    '/mailboxes/{address}/photo',
    response={200: MailboxV1, **errors(404, 422)},
    summary="Set a mailbox's profile photo",
    openapi_extra=_PHOTO_BODY,
)
@require_scope('mail.manage')
def api_set_mailbox_photo(request: ApiRequest, address: str) -> MailboxV1:
    """Upload a JPEG, PNG, WebP or GIF (multipart field ``photo``, up to 5 MB). The server cuts
    a square (the centre, or ``crop_x``/``crop_y``/``crop_size`` as fractions of the picture),
    stores two small JPEGs and removes all other data from the file. When the contact directory
    is on, contacts apps pick the photo up within minutes.

    The multipart body is read here, after the key's scope has been checked, so a key without
    ``mail.manage`` is refused (403) whatever it sends."""
    target = _address(address)
    upload = request.FILES.get('photo')
    if upload is None:
        raise HttpError(422, 'Send the picture as the multipart field "photo".')
    try:
        ops.ensure_plain(target)
    except MailboxError as exc:
        raise problem(exc) from exc
    user = _login(target)
    crop = None
    if request.POST.get('crop_size'):
        crop = Crop.parse(
            request.POST.get('crop_x') or '0',
            request.POST.get('crop_y') or '0',
            request.POST.get('crop_size', ''),
        )
        if crop is None:
            raise HttpError(422, 'The crop is outside the picture.')
    try:
        PhotoService.set_photo(user, upload.read(), crop)
    except PhotoError as exc:
        raise HttpError(422, str(exc)) from exc
    AuditService.record(action='api_mailbox_photo_set', user=actor(request), detail=target)
    row = ops.get_mailbox(target)
    if row is None:
        raise problem(MailboxError(f'{target} does not exist.'))
    return MailboxV1.of(row)


@router.delete(
    '/mailboxes/{address}/photo',
    response={204: None, **errors(404)},
    summary="Remove a mailbox's profile photo",
)
@require_scope('mail.manage')
def api_delete_mailbox_photo(request: ApiRequest, address: str) -> Status[None]:
    target = _address(address)
    try:
        ops.ensure_plain(target)
    except MailboxError as exc:
        raise problem(exc) from exc
    PhotoService.remove_photo(_login(target))
    AuditService.record(action='api_mailbox_photo_removed', user=actor(request), detail=target)
    return Status(204, None)


@router.get('/aliases', response={200: list[AliasV1], **errors()}, summary='List aliases')
@paginate(LimitOffsetPagination)
@require_scope('mail.manage')
def api_list_aliases(request: ApiRequest, domain: str | None = None) -> list[AliasV1]:
    """Aliases, ordered by domain then source. Filter with ``?domain=example.com``."""
    wanted = _address(domain) if domain else None
    return [AliasV1.of(a) for a in ops.list_aliases() if wanted is None or a.domain == wanted]


@router.post('/aliases', response={201: AliasV1, **errors(409, 422)}, summary='Create an alias')
@require_scope('mail.manage')
def api_create_alias(request: ApiRequest, payload: AliasCreateV1) -> Status[AliasV1]:
    """Forward ``source`` to ``destination``. Loops and clashes with mailboxes are refused."""
    try:
        created = ops.create_alias(
            AliasCreateIn(source=_address(payload.source), destination=payload.destination)
        )
    except MailboxError as exc:
        raise problem(exc) from exc
    AuditService.record(
        action='api_alias_created',
        user=actor(request),
        detail=f'{created.source} -> {created.destination}',
    )
    return Status(201, AliasV1.of(created))


@router.delete(
    '/aliases/{alias_id}', response={204: None, **errors(404)}, summary='Delete an alias'
)
@require_scope('mail.manage')
def api_delete_alias(request: ApiRequest, alias_id: str) -> Status[None]:
    try:
        ops.delete_alias(alias_id)
    except MailboxError as exc:
        raise problem(exc) from exc
    AuditService.record(action='api_alias_deleted', user=actor(request), detail=alias_id)
    return Status(204, None)


@router.post(
    '/messages',
    response={202: MessageAcceptedV1, **errors(403, 409, 413, 422, 502, 503)},
    summary='Send a message',
)
@require_scope('mail.send')
def api_send_message(
    request: ApiRequest,
    payload: MessageIn,
    idempotency_key: Annotated[str | None, Header(alias='Idempotency-Key')] = None,
) -> Status[MessageAcceptedV1]:
    """Send one message as one of the key's allowed senders.

    The server signs it with DKIM and delivers it like any other outgoing mail, under the same
    limits as a mailbox (recipients per message, blocked destinations, containment) plus the
    key's own daily cap. ``202`` means *accepted for delivery*, not delivered. Send an
    ``Idempotency-Key`` header (up to 64 characters) to make a retry safe: the same key and
    message return the first answer instead of sending twice.
    """
    row = request.auth.row
    sending = SendingKey(
        key_id=key_id(row.prefix),
        allowed_senders=tuple(row.allowed_senders or ()),
        daily_recipients=row.send_limit_per_day,
        sandbox=row.sandbox,
        prefix=row.prefix,
        name=row.name,
    )
    message = SendRequest(
        sender=payload.from_,
        to=tuple(payload.to),
        cc=tuple(payload.cc),
        bcc=tuple(payload.bcc),
        reply_to=payload.reply_to,
        subject=payload.subject,
        text=payload.text,
        html=payload.html,
    )
    token = (idempotency_key or '').strip()
    if len(token) > 64:
        raise HttpError(422, 'The Idempotency-Key is limited to 64 characters.')
    slot = f'apiidem:{sending.key_id}:{token}' if token else ''
    fingerprint = digest(payload.model_dump_json(by_alias=True))
    if slot:
        previous = cache.get(slot)
        if isinstance(previous, dict):
            if previous.get('fingerprint') != fingerprint:
                raise HttpError(422, 'That Idempotency-Key was used with a different message.')
            if previous.get('state') == 'pending':
                raise HttpError(409, 'A request with this Idempotency-Key is still in progress.')
            return Status(202, MessageAcceptedV1(**previous['receipt']))
        cache.set(slot, {'state': 'pending', 'fingerprint': fingerprint}, 300)
    try:
        receipt = MessageService.send(message, sending)
    except SendRefused as exc:
        if slot:
            cache.delete(slot)
        if exc.retry_after is not None:
            request.api_retry_after = exc.retry_after
        raise HttpError(exc.status, exc.message) from exc
    accepted = MessageAcceptedV1(
        id=receipt.message_id,
        status='captured' if receipt.captured else 'queued',
        recipients=receipt.recipients,
    )
    if slot:
        cache.set(
            slot,
            {'state': 'done', 'fingerprint': fingerprint, 'receipt': accepted.model_dump()},
            IDEMPOTENCY_TTL,
        )
    if not receipt.captured:
        from backend.apps.mail.services import delivery_events

        try:
            delivery_events.remember(
                receipt.message_id, row.prefix, message.sender.strip().lower(), receipt.recipients
            )
        except Exception:  # events are a convenience; the message is already on its way
            logger.warning('Could not record delivery events for %s', receipt.message_id)
    domains = sorted({a.rpartition('@')[2] for a in (*message.to, *message.cc, *message.bcc)})
    AuditService.record(
        action='api_message_captured' if receipt.captured else 'api_message_sent',
        user=actor(request),
        detail=f'{message.sender} -> {receipt.recipients} recipient(s) [{",".join(domains)}]',
    )
    return Status(202, accepted)


# ------------------------------------------------------------------------------ sandbox


def _sandbox_key(request: ApiRequest):  # noqa: ANN202
    row = request.auth.row
    if not row.sandbox:
        raise HttpError(403, 'Only a sandbox key has captured messages.')
    return row


@router.get(
    '/sandbox/messages',
    response={200: list[SandboxMessageV1], **errors()},
    summary='List captured sandbox messages',
)
@paginate(LimitOffsetPagination)
@require_scope('mail.send')
def api_sandbox_messages(request: ApiRequest, to: str | None = None) -> list[SandboxMessageV1]:
    """What this sandbox key sent, newest first. ``?to=`` keeps messages for one recipient. Only
    the calling key's own messages are listed."""
    from backend.apps.mail.services import sandbox

    row = _sandbox_key(request)
    return [SandboxMessageV1.of(m) for m in sandbox.messages_for(row.prefix, to=to)]


@router.get(
    '/sandbox/messages/{message_id}',
    response={200: SandboxMessageV1, **errors(404)},
    summary='Get a captured sandbox message',
)
@require_scope('mail.send')
def api_sandbox_message(request: ApiRequest, message_id: str) -> SandboxMessageV1:
    from backend.apps.mail.services import sandbox

    row = _sandbox_key(request)
    found = sandbox.get_for(row.prefix, message_id)
    if found is None:
        raise HttpError(404, 'No captured message with that id for this key.')
    return SandboxMessageV1.of(found)


@router.delete(
    '/sandbox/messages',
    response={204: None, **errors()},
    summary='Delete all captured sandbox messages',
)
@require_scope('mail.send')
def api_sandbox_clear(request: ApiRequest) -> Status[None]:
    """Start a test run with an empty sandbox."""
    from backend.apps.mail.services import sandbox

    row = _sandbox_key(request)
    sandbox.clear(row.prefix)
    return Status(204, None)


# ------------------------------------------------------------------------------ webhooks
# A key manages its own webhooks: they hear about the messages that key sends (and, with the
# Inbox Webhooks plugin, about mail received by the mailboxes they name).


def _own_webhook(request: ApiRequest, webhook_id: str):  # noqa: ANN202
    from backend.apps.mail.services import webhooks

    row = webhooks.get_endpoint(webhook_id, request.auth.row.prefix)
    if row is None:
        raise HttpError(404, 'No webhook with that id for this key.')
    return row


@router.get('/webhooks', response={200: list[WebhookV1], **errors()}, summary='List webhooks')
@require_scope('mail.send')
def api_list_webhooks(request: ApiRequest) -> list[WebhookV1]:
    """This key's webhooks."""
    from backend.apps.mail.services import webhooks

    return [WebhookV1.of(r) for r in webhooks.endpoints_for(request.auth.row.prefix)]


@router.post(
    '/webhooks', response={201: WebhookCreatedV1, **errors(422)}, summary='Create a webhook'
)
@require_scope('mail.send')
def api_create_webhook(request: ApiRequest, payload: WebhookCreateV1) -> Status[WebhookCreatedV1]:
    """Events: ``message.queued``, ``message.delivered``, ``message.deferred``,
    ``message.bounced`` (Delivery Events plugin) and ``message.received`` (Inbox Webhooks plugin,
    with ``mailboxes``). The answer carries the signing ``secret`` once: keep it, it verifies the
    ``X-Ifinmail-Signature`` header of every event."""
    from backend.apps.mail.services import webhooks

    if payload.mailboxes:
        _check_mailboxes(request, payload.mailboxes)
    try:
        row, secret = webhooks.create_endpoint(
            name=payload.name,
            url=payload.url,
            events=payload.events,
            owner_prefix=request.auth.row.prefix,
            mailboxes=payload.mailboxes,
            created_by=actor(request),
        )
    except webhooks.WebhookError as exc:
        raise HttpError(422, str(exc)) from exc
    AuditService.record(
        action='api_webhook_created', user=actor(request), detail=f'{row.name} {row.url}'
    )
    return Status(201, WebhookCreatedV1(**WebhookV1.of(row).model_dump(), secret=secret))


def _check_mailboxes(request: ApiRequest, mailboxes: list[str]) -> None:
    """A key may watch the agent inboxes it created; any other mailbox on this server needs
    ``mail.manage`` as well (reading people's mail is an administrator's power)."""
    from backend.apps.mail.services import agent_inboxes

    row = request.auth.row
    for box in mailboxes:
        address = box.strip().lower()
        if agent_inboxes.owns(row.prefix, address):
            continue
        if 'mail.manage' in (row.scopes or []) and ops.get_mailbox(address) is not None:
            continue
        raise HttpError(403, f'This key may not read mail for {box}.')


@router.delete(
    '/webhooks/{webhook_id}', response={204: None, **errors(404)}, summary='Delete a webhook'
)
@require_scope('mail.send')
def api_delete_webhook(request: ApiRequest, webhook_id: str) -> Status[None]:
    row = _own_webhook(request, webhook_id)
    AuditService.record(action='api_webhook_deleted', user=actor(request), detail=row.name)
    row.delete()
    return Status(204, None)


@router.post(
    '/webhooks/{webhook_id}/test',
    response={200: WebhookDeliveryV1, **errors(404)},
    summary='Send a test event',
)
@require_scope('mail.send')
def api_test_webhook(request: ApiRequest, webhook_id: str) -> WebhookDeliveryV1:
    """Sends ``webhook.ping`` now and returns how the receiver answered."""
    from backend.apps.mail.services import webhooks

    return WebhookDeliveryV1.of(webhooks.ping(_own_webhook(request, webhook_id)))


@router.get(
    '/webhooks/{webhook_id}/deliveries',
    response={200: list[WebhookDeliveryV1], **errors(404)},
    summary='Recent deliveries of a webhook',
)
@paginate(LimitOffsetPagination)
@require_scope('mail.send')
def api_webhook_deliveries(request: ApiRequest, webhook_id: str) -> list[WebhookDeliveryV1]:
    """Newest first, kept for 14 days: what was sent, how many attempts, the last answer."""
    row = _own_webhook(request, webhook_id)
    return [WebhookDeliveryV1.of(d) for d in row.deliveries.all()[:500]]


@router.post(
    '/webhooks/{webhook_id}/enable',
    response={200: WebhookV1, **errors(404)},
    summary='Switch a webhook back on',
)
@require_scope('mail.send')
def api_enable_webhook(request: ApiRequest, webhook_id: str) -> WebhookV1:
    """After a ``410 Gone`` switched it off, or after fixing the receiver."""
    from backend.apps.mail.services import webhooks

    row = _own_webhook(request, webhook_id)
    webhooks.set_active(row, True)
    return WebhookV1.of(row)


# ------------------------------------------------------------------------------ agent inboxes
# Scope agents.manage: a key reaches only the inboxes it created, never anyone else's mailbox.


def _inbox(request: ApiRequest, address: str):  # noqa: ANN202
    from backend.apps.mail.services import agent_inboxes

    try:
        if not agent_inboxes.settings().enabled:
            raise agent_inboxes.InboxError('Agent inboxes are off. Install the Agent inboxes plugin.', 403)
        return agent_inboxes.get(request.auth.row.prefix, address)
    except agent_inboxes.InboxError as exc:
        raise HttpError(exc.status, str(exc)) from exc


def _inbox_call(fn, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    from backend.apps.mail.services import agent_inboxes

    try:
        return fn(*args, **kwargs)
    except agent_inboxes.InboxError as exc:
        raise HttpError(exc.status, str(exc)) from exc


@router.post('/inboxes', response={201: InboxV1, **errors(409, 422, 503)}, summary='Create an agent inbox')
@require_scope('agents.manage')
def api_create_inbox(request: ApiRequest, payload: InboxCreateV1) -> Status[InboxV1]:
    """A real mailbox for an agent, on the plugin's domain. Only this key can read or delete it,
    the key may send as it (``mail.send``), and it expires after ``ttl_hours`` (0: never). Plus
    addressing works: mail to ``name+anything@`` arrives here."""
    from backend.apps.mail.services import agent_inboxes

    row = _inbox_call(
        agent_inboxes.create,
        request.auth.row.prefix,
        name=payload.name,
        label=payload.label,
        ttl_hours=payload.ttl_hours,
    )
    AuditService.record(action='api_inbox_created', user=actor(request), detail=row.address)
    return Status(201, InboxV1.of(row))


@router.get('/inboxes', response={200: list[InboxV1], **errors()}, summary='List agent inboxes')
@require_scope('agents.manage')
def api_list_inboxes(request: ApiRequest) -> list[InboxV1]:
    from backend.apps.mail.services import agent_inboxes

    return [InboxV1.of(r) for r in agent_inboxes.owned(request.auth.row.prefix)]


@router.get('/inboxes/{address}', response={200: InboxV1, **errors(404)}, summary='Get an agent inbox')
@require_scope('agents.manage')
def api_get_inbox(request: ApiRequest, address: str) -> InboxV1:
    return InboxV1.of(_inbox(request, address))


@router.delete('/inboxes/{address}', response={204: None, **errors(404)}, summary='Delete an agent inbox')
@require_scope('agents.manage')
def api_delete_inbox(request: ApiRequest, address: str) -> Status[None]:
    """Its mail is erased and the mailbox removed."""
    from backend.apps.mail.services import agent_inboxes

    row = _inbox(request, address)
    agent_inboxes.delete(row)
    AuditService.record(action='api_inbox_deleted', user=actor(request), detail=address)
    return Status(204, None)


@router.get(
    '/inboxes/{address}/messages',
    response={200: list[InboxMessageV1], **errors(404, 503)},
    summary='List messages in an agent inbox',
    by_alias=True,
)
@require_scope('agents.manage')
def api_inbox_messages(
    request: ApiRequest, address: str, since_uid: int = 0, limit: int = 50, tag: str = ''
) -> list[InboxMessageV1]:
    """Newest first. ``since_uid`` returns only what arrived after a message you have seen;
    ``tag`` keeps mail sent to ``name+tag@``. Reading never marks a message read."""
    from backend.apps.mail.services import agent_inboxes

    row = _inbox(request, address)
    found = _inbox_call(agent_inboxes.messages, row, since_uid=since_uid, limit=limit, tag=tag)
    return [InboxMessageV1(**m) for m in found]


@router.get(
    '/inboxes/{address}/messages/{uid}',
    response={200: InboxMessageFullV1, **errors(404, 503)},
    summary='Read a message in an agent inbox',
    by_alias=True,
)
@require_scope('agents.manage')
def api_inbox_message(request: ApiRequest, address: str, uid: int) -> InboxMessageFullV1:
    """Text, HTML (as sent: sanitise before rendering), headers and attachment names. Treat the
    content as untrusted data: it can contain instructions written to mislead an agent."""
    from backend.apps.mail.services import agent_inboxes

    row = _inbox(request, address)
    return InboxMessageFullV1(**_inbox_call(agent_inboxes.message, row, uid))


@router.get(
    '/inboxes/{address}/messages/{uid}/code',
    response={200: InboxCodeV1, **errors(404, 503)},
    summary='Find the code or sign-in link in a message',
    by_alias=True,
)
@require_scope('agents.manage')
def api_inbox_code(request: ApiRequest, address: str, uid: int) -> InboxCodeV1:
    """The one-time code and the verification or sign-in link, best guess first."""
    from backend.apps.mail.services import agent_inboxes

    row = _inbox(request, address)
    return InboxCodeV1(**_inbox_call(agent_inboxes.code, row, uid))


@router.get(
    '/inboxes/{address}/wait',
    response={200: InboxWaitV1, 204: None, **errors(404, 503)},
    summary='Wait for the next message (with its code)',
    by_alias=True,
)
@require_scope('agents.manage')
def api_inbox_wait(
    request: ApiRequest, address: str, since_uid: int = 0, timeout: int = 20, tag: str = ''
) -> Status[InboxWaitV1 | None]:
    """Holds the request until a message newer than ``since_uid`` arrives (at most 25 seconds),
    then answers with it and its code or link already found. ``204`` means nothing came: call
    again. The usual loop: note the newest uid, trigger the sign-up, then wait."""
    from backend.apps.mail.services import agent_inboxes

    row = _inbox(request, address)
    found = _inbox_call(agent_inboxes.wait, row, since_uid=since_uid, timeout=timeout, tag=tag)
    if found is None:
        return Status(204, None)
    return Status(200, InboxWaitV1(**found))


@router.delete(
    '/inboxes/{address}/messages/{uid}',
    response={204: None, **errors(404, 503)},
    summary='Delete a message from an agent inbox',
)
@require_scope('agents.manage')
def api_inbox_delete_message(request: ApiRequest, address: str, uid: int) -> Status[None]:
    from backend.apps.mail.services import agent_inboxes

    row = _inbox(request, address)
    _inbox_call(agent_inboxes.delete_message, row, uid)
    return Status(204, None)


__all__ = [
    'create_alias',
    'create_mailbox',
    'delete_alias',
    'delete_mailbox',
    'get_outbound_state',
    'list_aliases',
    'list_mailboxes',
    'render_outbound',
    'set_active',
    'set_admin',
    'set_max_hops',
    'set_password',
    'set_quota',
    'set_smart_host',
    'set_smtp_proxy',
]
