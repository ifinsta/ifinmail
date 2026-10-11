"""Self-service account page: display name and password (views -> forms -> services)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..forms.account import AccountPasswordForm, ProfileNameForm
from ..services.mfa import TOTPService
from ..services.profile import ProfileError, ProfileService
from ..types.permissions import PermissionCode
from .auth import require_perm

_CONSOLE = require_perm(PermissionCode.CONSOLE_ACCESS)


def _first_error(form: object) -> str:
    for field, errors in form.errors.items():  # type: ignore[attr-defined]
        label = _(field.replace('_', ' ').capitalize())
        return _('{label}: {error}').format(label=label, error=errors[0])
    return _('Please check the form.')


@login_required
@_CONSOLE
@require_GET
def account_page(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'admin/settings_account.html',
        {
            'active_section': 'account',
            'show_settings_icon': True,
            'mfa_status': TOTPService.status_for(request.user),
        },
    )


@login_required
@_CONSOLE
@require_POST
def account_name(request: HttpRequest) -> HttpResponse:
    form = ProfileNameForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:account')
    try:
        name = ProfileService.set_full_name(request.user, form.cleaned_data['full_name'])
    except ProfileError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:account')
    AuditService.record(action='profile_name_updated', user=request.user.email, detail=name)
    messages.success(request, _('Display name saved.'))
    return redirect('accounts:account')


@login_required
@_CONSOLE
@require_POST
def account_password(request: HttpRequest) -> HttpResponse:
    form = AccountPasswordForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:account')
    try:
        ProfileService.change_password(
            request.user, form.cleaned_data['old_password'], form.cleaned_data['new_password']
        )
    except ProfileError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:account')
    # Keep this session signed in; other sessions die with the old password.
    update_session_auth_hash(request, request.user)
    AuditService.record(action='password_changed', user=request.user.email, detail='self-service')
    messages.success(request, _('Your password has been changed.'))
    return redirect('accounts:account')
