"""Settings → Suppressions: recipients API mail is never sent to, and keys paused for bounces."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..types.permissions import PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.MAIL_MANAGE)


def _actor(request: HttpRequest) -> str:
    return getattr(request.user, 'email', '') or 'console'


@login_required
@_MANAGE
@require_GET
def suppressions_page(request: HttpRequest) -> HttpResponse:
    from backend.apps.accounts.services.tokens import TokenService, key_id
    from backend.apps.domains.models import Domain
    from backend.apps.mail.services import compliance

    wanted = request.GET.get('q', '').strip().lower()
    rows = compliance.listing(None)
    if wanted:
        rows = [r for r in rows if wanted in r.address or wanted in r.domain]
    paused = []
    for key in TokenService.list_all():
        state = compliance.paused(key.prefix)
        if state:
            paused.append({'prefix': key.prefix, 'label': f'{key.name} ({key_id(key.prefix)})', **state})
    return render(
        request,
        'admin/settings_suppressions.html',
        {
            'active_section': 'suppressions',
            'show_settings_icon': True,
            'rows': rows[:500],
            'query': wanted,
            'domains': list(Domain.objects.order_by('name').values_list('name', flat=True)),
            'paused': paused,
            'policy': compliance.settings(),
        },
    )


@login_required
@_MANAGE
@require_POST
def suppressions_action(request: HttpRequest) -> HttpResponse:
    from backend.apps.mail.models import Suppression
    from backend.apps.mail.services import compliance
    from backend.apps.mail.services.messages import SendRefused, address

    action = request.POST.get('action', '')
    domain = request.POST.get('domain', '').strip().lower()
    if action == 'add':
        try:
            clean = address(request.POST.get('address', ''))
        except SendRefused as exc:
            messages.error(request, exc.message)
            return redirect('accounts:suppressions')
        if compliance.suppress(domain, clean, Suppression.MANUAL, by=_actor(request)):
            AuditService.record(action='suppression_added', user=_actor(request), detail=f'{clean} ({domain})')
            messages.success(request, f'{clean} will not get API mail from {domain}.')
        else:
            messages.error(request, f'{clean} is already suppressed for {domain}.')
    elif action == 'remove':
        clean = request.POST.get('address', '').strip().lower()
        if compliance.unsuppress(domain, clean):
            AuditService.record(action='suppression_removed', user=_actor(request), detail=f'{clean} ({domain})')
            messages.success(request, f'{clean} removed from the list.')
    elif action == 'resume':
        prefix = request.POST.get('prefix', '')
        compliance.resume(prefix)
        AuditService.record(action='api_key_resumed', user=_actor(request), detail=f'ifm_{prefix}')
        messages.success(request, 'The key may send again; its bounce counters start from zero.')
    return redirect('accounts:suppressions')
