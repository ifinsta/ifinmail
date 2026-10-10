"""Mailbox and alias management pages (web flow: views -> forms -> services)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.domains.services import DomainService
from backend.apps.mail.services import AliasService, MailboxService
from backend.apps.mail.types.provisioning import MailboxError
from backend.services.audit import AuditService

from ..forms.mailboxes import (
    AliasCreateForm,
    AliasDeleteForm,
    MailboxActionForm,
    MailboxCreateForm,
    RegistrationToggleForm,
)
from ..services.registration_policy import registration_open, set_registration_open
from .auth import _is_staff

_STAFF = user_passes_test(_is_staff, login_url='accounts:login')
_MB = 1024 * 1024


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def _first_error(form: MailboxCreateForm | MailboxActionForm | AliasCreateForm) -> str:
    for field, errors in form.errors.items():
        label = field.replace('_', ' ').capitalize()
        return f'{label}: {errors[0]}'
    return 'Please check the form.'


def _quota_label(quota_bytes: int) -> str:
    return 'Unlimited' if not quota_bytes else f'{quota_bytes // _MB} MB'


@login_required
@_STAFF
@require_GET
def mailboxes_page(request: HttpRequest) -> HttpResponse:
    rows = [
        {'row': r, 'quota_label': _quota_label(r.quota_bytes), 'quota_mb': r.quota_bytes // _MB}
        for r in MailboxService.list_rows()
    ]
    return render(
        request,
        'admin/settings_mailboxes.html',
        {
            'active_section': 'mailboxes',
            'show_settings_icon': True,
            'domains': [d.name for d in DomainService.get_all_domains()],
            'mailboxes': rows,
            'registration_open': registration_open(),
        },
    )


@login_required
@_STAFF
@require_POST
def mailboxes_create(request: HttpRequest) -> HttpResponse:
    form = MailboxCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:mailboxes')
    try:
        mailbox, _user = MailboxService.create(
            form.cleaned_data['domain'],
            form.cleaned_data['local_part'],
            form.cleaned_data['password'],
            quota_bytes=form.quota_bytes,
            is_admin=form.cleaned_data['is_admin'],
        )
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailboxes')
    address = MailboxService.address_for(mailbox)
    AuditService.record(action='mailbox_created', user=_actor(request), detail=address)
    messages.success(request, f'Created {address}.')
    return redirect('accounts:mailboxes')


@login_required
@_STAFF
@require_POST
def mailboxes_action(request: HttpRequest) -> HttpResponse:
    form = MailboxActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:mailboxes')
    action, address = form.cleaned_data['action'], form.cleaned_data['address'].lower()
    try:
        if action == 'password':
            MailboxService.set_password(address, form.cleaned_data['password'])
            if address == (request.user.email or '').lower():
                # Changing your own password must not sign you out.
                request.user.refresh_from_db()
                update_session_auth_hash(request, request.user)
            message = f'Password changed for {address}.'
        elif action == 'quota':
            MailboxService.set_quota(address, form.quota_bytes)
            message = f'Quota for {address} set to {_quota_label(form.quota_bytes)}.'
        elif action in ('enable', 'disable'):
            if address == (request.user.email or '').lower() and action == 'disable':
                raise MailboxError('You cannot disable your own account.')
            MailboxService.set_active(address, action == 'enable')
            message = f'{address} {"enabled" if action == "enable" else "disabled"}.'
        else:
            if address == (request.user.email or '').lower():
                raise MailboxError('You cannot delete your own account.')
            MailboxService.delete(address)
            message = f'Removed {address}. Its stored mail was left on disk.'
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailboxes')
    AuditService.record(action=f'mailbox_{action}', user=_actor(request), detail=address)
    messages.success(request, message)
    return redirect('accounts:mailboxes')


@login_required
@_STAFF
@require_POST
def registration_toggle(request: HttpRequest) -> HttpResponse:
    form = RegistrationToggleForm(request.POST)
    if form.is_valid():
        enabled = form.cleaned_data['open']
        set_registration_open(enabled)
        AuditService.record(
            action='registration_toggle',
            user=_actor(request),
            detail='open' if enabled else 'closed',
        )
        messages.success(
            request,
            'Self-registration is now open.' if enabled else 'Self-registration is now closed.',
        )
    return redirect('accounts:mailboxes')


@login_required
@_STAFF
@require_GET
def aliases_page(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'admin/settings_aliases.html',
        {
            'active_section': 'aliases',
            'show_settings_icon': True,
            'domains': [d.name for d in DomainService.get_all_domains()],
            'aliases': AliasService.list_rows(),
        },
    )


@login_required
@_STAFF
@require_POST
def aliases_create(request: HttpRequest) -> HttpResponse:
    form = AliasCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:aliases')
    try:
        alias = AliasService.create(form.source, form.cleaned_data['destination'])
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:aliases')
    AuditService.record(
        action='alias_created',
        user=_actor(request),
        detail=f'{alias.source} -> {alias.destination}',
    )
    messages.success(request, f'{alias.source} now forwards to {alias.destination}.')
    return redirect('accounts:aliases')


@login_required
@_STAFF
@require_POST
def aliases_delete(request: HttpRequest) -> HttpResponse:
    form = AliasDeleteForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That alias could not be found.')
        return redirect('accounts:aliases')
    try:
        AliasService.delete(str(form.cleaned_data['alias_id']))
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:aliases')
    AuditService.record(
        action='alias_deleted', user=_actor(request), detail=str(form.cleaned_data['alias_id'])
    )
    messages.success(request, 'Alias removed.')
    return redirect('accounts:aliases')
