"""mail — api.py: the mail routes of the v1 API (urls.py → api.py → viewsets/ contract).

Mailboxes and aliases for integrations. Scope: ``mail.manage``. Mailboxes whose login has console
access are read-only here (see ``viewsets.mailboxes.ensure_plain``); the plain re-exports below
stay for in-process callers and tests.
"""

from ninja import Router, Status
from ninja.pagination import LimitOffsetPagination, paginate

from backend.apps.accounts.viewsets.auth import actor, require_scope
from backend.apps.accounts.viewsets.errors import problem
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.mail.serializers import (
    AliasCreateV1,
    AliasV1,
    MailboxCreateIn,
    MailboxCreateV1,
    MailboxUpdateV1,
    MailboxV1,
)
from backend.apps.mail.services.mailboxes import split_address
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

router = Router(tags=['mailboxes', 'aliases'])


def _address(raw: str) -> str:
    return raw.strip().lower()


@router.get('/mailboxes', response=list[MailboxV1], summary='List mailboxes')
@paginate(LimitOffsetPagination)
@require_scope('mail.manage')
def api_list_mailboxes(request, domain: str | None = None):
    """Mailboxes, ordered by domain then name. Filter with ``?domain=example.com``."""
    wanted = _address(domain) if domain else None
    rows = ops.list_mailboxes()
    return [MailboxV1.of(r) for r in rows if wanted is None or r.domain == wanted]


@router.post('/mailboxes', response={201: MailboxV1}, summary='Create a mailbox')
@require_scope('mail.manage')
def api_create_mailbox(request, payload: MailboxCreateV1):
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


@router.get('/mailboxes/{address}', response=MailboxV1, summary='Get a mailbox')
@require_scope('mail.manage')
def api_get_mailbox(request, address: str):
    row = ops.get_mailbox(_address(address))
    if row is None:
        raise problem(MailboxError(f'{_address(address)} does not exist.'))
    return MailboxV1.of(row)


@router.patch('/mailboxes/{address}', response=MailboxV1, summary='Change a mailbox')
@require_scope('mail.manage')
def api_update_mailbox(request, address: str, payload: MailboxUpdateV1):
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
    assert row is not None
    return MailboxV1.of(row)


@router.delete('/mailboxes/{address}', response={204: None}, summary='Delete a mailbox')
@require_scope('mail.manage')
def api_delete_mailbox(request, address: str):
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


@router.get('/aliases', response=list[AliasV1], summary='List aliases')
@paginate(LimitOffsetPagination)
@require_scope('mail.manage')
def api_list_aliases(request, domain: str | None = None):
    wanted = _address(domain) if domain else None
    return [AliasV1.of(a) for a in ops.list_aliases() if wanted is None or a.domain == wanted]


@router.post('/aliases', response={201: AliasV1}, summary='Create an alias')
@require_scope('mail.manage')
def api_create_alias(request, payload: AliasCreateV1):
    from backend.apps.mail.serializers import AliasCreateIn

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


@router.delete('/aliases/{alias_id}', response={204: None}, summary='Delete an alias')
@require_scope('mail.manage')
def api_delete_alias(request, alias_id: str):
    try:
        ops.delete_alias(alias_id)
    except MailboxError as exc:
        raise problem(exc) from exc
    AuditService.record(action='api_alias_deleted', user=actor(request), detail=alias_id)
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
