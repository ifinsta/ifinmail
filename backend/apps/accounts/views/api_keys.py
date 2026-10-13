"""API keys: the credentials integrations use to call ``/api/v1``.

A key is created by an administrator for an integration; the secret is shown once, here, right
after creation or rotation. Scopes can never exceed what the person creating the key holds, and
they keep being intersected with that person's permissions on every call.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..forms.mailboxes import ApiKeyActionForm, ApiKeyCreateForm
from ..services.roles import RoleService
from ..services.stepup import StepUpService
from ..services.tokens import (
    MAX_GRACE_HOURS,
    MAX_TOKEN_DAYS,
    TokenError,
    TokenService,
    key_id,
)
from ..types.permissions import TOKEN_SCOPES, PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.USERS_MANAGE)
_SESSION_SECRET = 'api_key_secret'


def _actor(request: HttpRequest) -> str:
    return getattr(request.user, 'email', '') or 'unknown'


@login_required
@_MANAGE
@require_GET
def api_keys(request: HttpRequest) -> HttpResponse:
    held = RoleService.effective_permissions(request.user)
    revealed = request.session.pop(_SESSION_SECRET, None)
    return render(
        request,
        'admin/settings_api_keys.html',
        {
            'active_section': 'api-keys',
            'show_settings_icon': True,
            'keys': TokenService.list_all(),
            'scope_choices': [code for code in TOKEN_SCOPES if code in held],
            'max_days': MAX_TOKEN_DAYS,
            'max_grace': MAX_GRACE_HOURS,
            'revealed': revealed,
        },
    )


@login_required
@_MANAGE
@require_POST
def api_key_create(request: HttpRequest) -> HttpResponse:
    form = ApiKeyCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That key request could not be read.')
        return redirect('accounts:api_keys')
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:api_keys')
    data = form.cleaned_data
    try:
        row, plain = TokenService.create(
            request.user,
            data['name'],
            list(data['scopes'] or []),
            expires_in_days=data['expires_in_days'],
            allowed_networks=data['networks'],
            rate_limit_per_minute=data['rate_limit_per_minute'],
        )
    except TokenError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:api_keys')
    request.session[_SESSION_SECRET] = {
        'name': row.name,
        'key': key_id(row.prefix),
        'token': plain,
        'secret': plain.split('.', 2)[2],
    }
    AuditService.record(
        action='api_key_created',
        user=_actor(request),
        detail=f'{key_id(row.prefix)} {row.name} scopes={",".join(row.scopes)}'
        + (f' networks={",".join(row.allowed_networks)}' if row.allowed_networks else ''),
    )
    messages.success(request, f'Key {row.name} created. Copy the secret below; it is shown once.')
    return redirect('accounts:api_keys')


@login_required
@_MANAGE
@require_POST
def api_key_action(request: HttpRequest) -> HttpResponse:
    form = ApiKeyActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That key request could not be read.')
        return redirect('accounts:api_keys')
    row = TokenService.get(str(form.cleaned_data['token_id']))
    if row is None:
        messages.error(request, 'That key is already gone.')
        return redirect('accounts:api_keys')
    try:
        if form.cleaned_data['action'] == 'rotate':
            problem = StepUpService.confirm(request)
            if problem:
                messages.error(request, problem)
                return redirect('accounts:api_keys')
            grace = form.cleaned_data['grace_hours'] or 0
            row, plain = TokenService.rotate(row.user, str(row.id), grace_hours=grace)
            request.session[_SESSION_SECRET] = {
                'name': row.name,
                'key': key_id(row.prefix),
                'token': plain,
                'secret': plain.split('.', 2)[2],
            }
            AuditService.record(
                action='api_key_rotated',
                user=_actor(request),
                detail=f'{key_id(row.prefix)} overlap={grace}h',
            )
            messages.success(
                request,
                f'Key {row.name} rotated. Copy the new secret below.'
                + (f' The old one keeps working for {grace} hours.' if grace else ''),
            )
        else:
            TokenService.revoke(row.user, str(row.id))
            AuditService.record(
                action='api_key_revoked', user=_actor(request), detail=key_id(row.prefix)
            )
            messages.success(request, f'Key {row.name} revoked. It stops working immediately.')
    except TokenError as exc:
        messages.error(request, str(exc))
    return redirect('accounts:api_keys')
