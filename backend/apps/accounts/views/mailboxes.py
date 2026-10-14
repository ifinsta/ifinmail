"""Mailbox and alias management pages (web flow: views -> forms -> services)."""

from __future__ import annotations

import logging
import os
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.domains.services import DomainService
from backend.apps.mail.services import (
    AliasService,
    MailboxInviteService,
    MailboxService,
    QuotaService,
)
from backend.apps.mail.types.provisioning import MailboxError
from backend.apps.mail.types.quota import DEFAULT_QUOTA_MB, MB, QuotaBudget, human_bytes
from backend.config import site_url
from backend.config.branding import email_brand_context

from ..forms.mailboxes import (
    AliasCreateForm,
    AliasDeleteForm,
    MailboxActionForm,
    MailboxCreateForm,
    MailboxSetupForm,
    RegistrationToggleForm,
)
from ..services.registration_policy import registration_open, set_registration_open
from ..services.stepup import StepUpService
from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')

_MAIL = require_perm(PermissionCode.MAIL_MANAGE)

_MB = MB

# Changes to who can do what, or that destroy a login, ask for the password again.
_STEP_UP_ACTIONS = ('delete', 'grant_admin', 'revoke_admin')


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def _first_error(
    form: MailboxCreateForm | MailboxActionForm | AliasCreateForm | MailboxSetupForm,
) -> str:
    for field, errors in form.errors.items():
        label = field.replace('_', ' ').capitalize()
        return f'{label}: {errors[0]}'
    return 'Please check the form.'


def _quota_label(quota_bytes: int) -> str:
    return 'Unlimited' if not quota_bytes else f'{quota_bytes // _MB} MB'


def _quota_budget_context() -> dict[str, object]:
    """Template-ready space budget (disk, allocated, headroom)."""
    budget = QuotaService.get_budget()
    headroom = budget.headroom_bytes
    disk_total, disk_free = budget.disk_total_bytes, budget.disk_free_bytes

    if disk_total is None or disk_free is None:
        disk_status = 'info'
    else:
        used_pct = (disk_total - disk_free) / disk_total * 100 if disk_total else 0
        disk_status = 'ok' if used_pct < 80 else ('warn' if used_pct < 95 else 'err')

    if headroom is None:
        available_status = 'info'
    elif headroom < 0:
        available_status = 'err'
    elif budget.available_bytes and headroom < budget.available_bytes * 0.2:
        available_status = 'warn'
    else:
        available_status = 'ok'

    return {
        'disk_total': human_bytes(disk_total),
        'disk_free': human_bytes(disk_free),
        'disk_status': disk_status,
        'allocated': human_bytes(budget.allocated_bytes),
        'stored': human_bytes(budget.stored_bytes),
        'headroom': human_bytes(headroom),
        'headroom_mb': (headroom // _MB) if headroom is not None else None,
        'available_status': available_status,
        'overcommit_by': human_bytes(-headroom) if headroom is not None and headroom < 0 else None,
        'overcommitted': budget.overcommitted,
        'unknown': disk_total is None,
        'mailbox_count': budget.mailbox_count,
        'unlimited_count': budget.unlimited_count,
        'allocated_bytes': budget.allocated_bytes,
        'headroom_bytes': headroom,
    }


def _warn_if_overcommitted(request: HttpRequest, before: QuotaBudget | None) -> None:
    """Warn when this change pushed the promised quota past the available room.

    Quotas stay soft promises (overcommit is allowed), but the admin sees it.
    """
    after = QuotaService.get_budget()
    if after.headroom_bytes is None:
        return
    if after.overcommitted and (before is None or after.allocated_bytes > before.allocated_bytes):
        messages.warning(
            request,
            f'Heads-up: mailboxes now promise {human_bytes(after.allocated_bytes)} in total. '
            f'Filling them would need {human_bytes(-after.headroom_bytes)} more than the '
            'space available on the mail volume — the disk can fill up before the quotas do.',
        )


@login_required
@_MAIL
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
            'default_quota_mb': DEFAULT_QUOTA_MB,
            'quota_budget': _quota_budget_context(),
        },
    )


def _setup_url(request: HttpRequest, address: str) -> str:
    """Absolute single-use setup link for ``address`` (raises MailboxError if unknown)."""
    uid, token = MailboxInviteService.make_token(address)
    path = reverse('accounts:mailbox_setup', kwargs={'uidb64': uid, 'token': token})
    try:
        return f'{site_url.origin(request)}{path}'
    except Exception:
        return path


def _send_setup_email(request: HttpRequest, address: str, link: str, send_to: str) -> bool:
    """Email the setup link and getting-started instructions; False if it could not be sent."""
    days = max(1, settings.PASSWORD_RESET_TIMEOUT // 86400)
    context = {
        'address': address,
        'setup_url': link,
        'valid_days': days,
        'mail_host': os.environ.get('MAIL_HOSTNAME', ''),
        **email_brand_context(site_url.builder(request)),
    }
    html_body = render_to_string('admin/email_mailbox_setup.html', context)
    try:
        send_mail(
            f'Set up your mailbox {address}',
            render_to_string('admin/email_mailbox_setup.txt', context),
            None,
            [send_to],
            html_message=html_body,
        )
    except (SMTPException, ConnectionError, OSError) as exc:
        logger.warning('Failed to send the setup link for %s to %s: %s', address, send_to, exc)
        return False
    return True


@login_required
@_MAIL
@require_POST
def mailboxes_create(request: HttpRequest) -> HttpResponse:
    form = MailboxCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:mailboxes')
    before = QuotaService.get_budget()
    try:
        mailbox, _user = MailboxService.create(
            form.cleaned_data['domain'],
            form.cleaned_data['local_part'],
            None,  # invite-pending: the owner sets their own password via link
            quota_bytes=form.quota_bytes,
            is_admin=form.cleaned_data['is_admin'],
        )
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailboxes')
    address = MailboxService.address_for(mailbox)
    AuditService.record(action='mailbox_created', user=_actor(request), detail=address)
    _warn_if_overcommitted(request, before)
    try:
        link = _setup_url(request, address)
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailboxes')
    AuditService.record(action='mailbox_invite_issued', user=_actor(request), detail=address)
    send_to = form.cleaned_data['send_to']
    if send_to and _send_setup_email(request, address, link, send_to):
        AuditService.record(
            action='mailbox_invite_sent', user=_actor(request), detail=f'{address} -> {send_to}'
        )
        messages.success(
            request,
            f'Created {address}. The setup link and getting-started instructions '
            f'were sent to {send_to}.',
        )
    elif send_to:
        messages.warning(
            request,
            f'Created {address}, but the email to {send_to} could not be sent. Share this '
            f'one-time setup link so the owner can set their password: {link}',
        )
    else:
        messages.success(
            request,
            f'Created {address}. Share this one-time setup link so the owner '
            f'can set their password: {link}',
        )
    return redirect('accounts:mailboxes')


@login_required
@_MAIL
@require_POST
def mailboxes_action(request: HttpRequest) -> HttpResponse:
    form = MailboxActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('accounts:mailboxes')
    action, address = form.cleaned_data['action'], form.cleaned_data['address'].lower()
    if action in _STEP_UP_ACTIONS:
        problem = StepUpService.confirm(request)
        if problem:
            messages.error(request, problem)
            return redirect('accounts:mailboxes')
    before = QuotaService.get_budget()
    try:
        if action == 'invite':
            link = _setup_url(request, address)
            audit_action = 'mailbox_invite_issued'
            send_to = form.cleaned_data['send_to']
            if send_to and _send_setup_email(request, address, link, send_to):
                AuditService.record(action=audit_action, user=_actor(request), detail=address)
                AuditService.record(
                    action='mailbox_invite_sent',
                    user=_actor(request),
                    detail=f'{address} -> {send_to}',
                )
                messages.success(
                    request,
                    f'A new setup link for {address} and getting-started instructions '
                    f'were sent to {send_to}.',
                )
                mailbox_id = MailboxService.mailbox_id_for(address)
                if form.cleaned_data.get('return_to') == 'profile' and mailbox_id is not None:
                    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
                return redirect('accounts:mailboxes')
            if send_to:
                messages.warning(
                    request,
                    f'The email to {send_to} could not be sent. Share the link yourself.',
                )
            if form.cleaned_data.get('return_to') == 'profile':
                # One-time handoff: the profile page shows the link in a
                # copyable panel instead of a wall of text in a flash message.
                request.session['invite_link'] = {'address': address, 'link': link}
                AuditService.record(action=audit_action, user=_actor(request), detail=address)
                messages.success(
                    request,
                    f'Setup link ready for {address} — copy it below. It is single-use.',
                )
                mailbox_id = MailboxService.mailbox_id_for(address)
                if mailbox_id is not None:
                    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
            message = f'Setup link for {address} (single-use, expires automatically): {link}'
        elif action == 'quota':
            MailboxService.set_quota(address, form.quota_bytes)
            message = f'Quota for {address} set to {_quota_label(form.quota_bytes)}.'
        elif action in ('enable', 'disable'):
            if address == (request.user.email or '').lower() and action == 'disable':
                raise MailboxError('You cannot disable your own account.')
            MailboxService.set_active(address, action == 'enable')
            message = f'{address} {"enabled" if action == "enable" else "disabled"}.'
        elif action in ('grant_admin', 'revoke_admin'):
            if address == (request.user.email or '').lower():
                raise MailboxError('Your own admin rights cannot be changed here.')
            MailboxService.set_admin(address, action == 'grant_admin')
            message = (
                f'{address} can now sign in to the admin console.'
                if action == 'grant_admin'
                else f'{address} can no longer sign in to the admin console.'
            )
        else:
            if address == (request.user.email or '').lower():
                raise MailboxError('You cannot delete your own account.')
            MailboxService.delete(address)
            message = f'Removed {address}. Its stored mail was left on disk.'
    except MailboxError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailboxes')
    audit_action = locals().get('audit_action', f'mailbox_{action}')
    AuditService.record(action=audit_action, user=_actor(request), detail=address)
    if action == 'quota':
        _warn_if_overcommitted(request, before)
    messages.success(request, message)
    return redirect('accounts:mailboxes')


def mailbox_setup(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    """Public single-use link where the mailbox owner sets their own password."""
    user = MailboxInviteService.check_token(uidb64, token)
    if user is None:
        return render(
            request,
            'admin/mailbox_setup.html',
            {'valid': False, 'address': ''},
        )
    if request.method == 'POST':
        # Capture the viewer BEFORE the password change: request.user is lazy,
        # and first evaluating it after accept() would see a stale session hash
        # (for one's own link) and Django would flush the session.
        viewer_email = (request.user.email or '').lower() if request.user.is_authenticated else ''
        form = MailboxSetupForm(request.POST)
        if form.is_valid():
            try:
                updated = MailboxInviteService.accept(uidb64, token, form.cleaned_data['password'])
            except MailboxError as exc:
                return render(
                    request,
                    'admin/mailbox_setup.html',
                    {'valid': True, 'address': user.email, 'error': str(exc)},
                )
            AuditService.record(
                action='mailbox_invite_accepted', user=updated.email, detail=updated.email
            )
            if viewer_email and viewer_email == updated.email.lower():
                # Setting your own password must not sign you out.
                request.user.refresh_from_db()
                update_session_auth_hash(request, request.user)
            messages.success(
                request, f'Password set for {updated.email}. Sign in with your new password.'
            )
            return redirect('accounts:login')
        return render(
            request,
            'admin/mailbox_setup.html',
            {'valid': True, 'address': user.email, 'error': _first_error(form)},
        )
    return render(request, 'admin/mailbox_setup.html', {'valid': True, 'address': user.email})


@login_required
@_MAIL
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
@_MAIL
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
@_MAIL
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
@_MAIL
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
