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

router = Router(tags=['mailboxes', 'aliases', 'messages'])
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
        id=receipt.message_id, status='queued', recipients=receipt.recipients
    )
    if slot:
        cache.set(
            slot,
            {'state': 'done', 'fingerprint': fingerprint, 'receipt': accepted.model_dump()},
            IDEMPOTENCY_TTL,
        )
    domains = sorted({a.rpartition('@')[2] for a in (*message.to, *message.cc, *message.bcc)})
    AuditService.record(
        action='api_message_sent',
        user=actor(request),
        detail=f'{message.sender} -> {receipt.recipients} recipient(s) [{",".join(domains)}]',
    )
    return Status(202, accepted)


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
