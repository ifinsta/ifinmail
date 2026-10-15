"""Settings → Webhooks: where the server sends events (delivery outcomes, received mail).

Webhooks created here hear about every message sent through the API; a key can also create its
own through the API, which hear only about that key's messages. Both are listed here.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..types.permissions import PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.USERS_MANAGE)
_SESSION_SECRET = 'webhook_secret'


def _actor(request: HttpRequest) -> str:
    return getattr(request.user, 'email', '') or 'unknown'


@login_required
@_MANAGE
@require_GET
def webhooks_page(request: HttpRequest) -> HttpResponse:
    from backend.apps.accounts.services.tokens import TokenService, key_id
    from backend.apps.mail.services import webhooks
    from backend.apps.mail.types.events import DESCRIPTIONS, SUBSCRIBABLE

    current = webhooks.policy()
    owners = {k.prefix: f'{k.name} ({key_id(k.prefix)})' for k in TokenService.list_all()}
    rows = []
    for row in webhooks.endpoints_for(None):
        rows.append(
            {
                'row': row,
                'owner': owners.get(row.owner_prefix, '') if row.owner_prefix else '',
                'recent': list(row.deliveries.all()[:5]),
            }
        )
    return render(
        request,
        'admin/settings_webhooks.html',
        {
            'active_section': 'webhooks',
            'show_settings_icon': True,
            'rows': rows,
            'policy': current,
            'events': [(e, DESCRIPTIONS[e]) for e in SUBSCRIBABLE],
            'revealed': request.session.pop(_SESSION_SECRET, None),
        },
    )


@login_required
@_MANAGE
@require_POST
def webhooks_create(request: HttpRequest) -> HttpResponse:
    from backend.apps.mail.services import webhooks

    boxes = [
        b.strip()
        for b in request.POST.get('mailboxes', '').replace(',', '\n').splitlines()
        if b.strip()
    ]
    try:
        row, secret = webhooks.create_endpoint(
            name=request.POST.get('name', ''),
            url=request.POST.get('url', ''),
            events=request.POST.getlist('events'),
            mailboxes=boxes,
            created_by=_actor(request),
        )
    except webhooks.WebhookError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:webhooks')
    request.session[_SESSION_SECRET] = {'name': row.name, 'secret': secret}
    AuditService.record(action='webhook_created', user=_actor(request), detail=f'{row.name} {row.url}')
    messages.success(request, f'Webhook {row.name} created. Copy its signing secret below.')
    return redirect('accounts:webhooks')


@login_required
@_MANAGE
@require_POST
def webhooks_action(request: HttpRequest) -> HttpResponse:
    from backend.apps.mail.services import webhooks

    row = webhooks.get_endpoint(request.POST.get('webhook', ''), None)
    if row is None:
        messages.error(request, 'That webhook is already gone.')
        return redirect('accounts:webhooks')
    action = request.POST.get('action', '')
    if action == 'test':
        delivery = webhooks.ping(row)
        if delivery.status == delivery.DELIVERED:
            messages.success(request, f'{row.name} answered {delivery.last_status_code}.')
        else:
            messages.error(request, f'{row.name}: {delivery.last_error or "no answer"}.')
    elif action in ('enable', 'disable'):
        webhooks.set_active(row, action == 'enable')
        messages.success(request, f'{row.name} is {"on" if action == "enable" else "off"}.')
    elif action == 'delete':
        AuditService.record(action='webhook_deleted', user=_actor(request), detail=row.name)
        row.delete()
        messages.success(request, 'Webhook removed.')
    return redirect('accounts:webhooks')
